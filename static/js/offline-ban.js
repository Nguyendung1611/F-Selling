/* Bán hàng khi mất mạng: hàng chờ trong IndexedDB + tự đồng bộ.
 *
 * CỐ Ý tách hẳn khỏi pos.js. File kia 94KB và giữ toàn bộ luồng thu tiền; mọi
 * logic offline nằm ở đây, pos.js chỉ có vài điểm nối ngắn gọi sang.
 *
 * ===================== LUẬT AN TOÀN QUAN TRỌNG NHẤT =====================
 *
 * Chỉ lưu phiếu offline khi `navigator.onLine === false`.
 *
 * Vì sao không lưu mỗi khi gọi API hỏng: một lỗi mạng có thể xảy ra SAU khi
 * server đã tạo đơn xong (mất sóng lúc nhận phản hồi). Lưu phiếu offline lúc đó
 * là ghi đơn HAI LẦN — một từ request gốc, một từ phiếu — với hai khóa khác
 * nhau nên không khóa idempotency nào chặn được.
 *
 * `navigator.onLine === false` nghĩa là máy không có đường mạng nào, tức là
 * request chưa từng rời khỏi máy. Đây là điều kiện chặt: mạng chập chờn (onLine
 * = true nhưng không tới được server) sẽ KHÔNG đi đường offline, mà rơi vào cơ
 * chế retry theo `operation_id` sẵn có của pos.js — thứ vốn được viết ra đúng
 * cho tình huống đó.
 *
 * Thà bỏ lỡ vài ca đáng lẽ lưu offline được, còn hơn ghi trùng một đơn tiền.
 *
 * ===================== PHIẾU HỎNG THÌ GIỮ, KHÔNG XÓA =====================
 *
 * Server trả 4xx nghĩa là phiếu này sẽ không bao giờ ghi được (sai định dạng,
 * uuid trùng shop khác...). Xóa đi là mất trắng dấu vết một lần bán có thật.
 * Đánh dấu `loi` rồi giữ lại, và không thử lại nữa để nó không chặn hàng chờ.
 */
(function (global) {
    'use strict';

    const TEN_DB = 'fselling-offline';
    const PHIEN_BAN = 1;
    const KHO_PHIEU = 'phieu';
    const KHO_ANH_CHUP = 'anhchup';

    let _db = null;

    function moDB() {
        if (_db) return Promise.resolve(_db);
        return new Promise(function (ok, that_bai) {
            const yc = indexedDB.open(TEN_DB, PHIEN_BAN);
            yc.onupgradeneeded = function () {
                const db = yc.result;
                if (!db.objectStoreNames.contains(KHO_PHIEU)) {
                    const kho = db.createObjectStore(KHO_PHIEU, { keyPath: 'offline_uuid' });
                    kho.createIndex('shop_id', 'shop_id', { unique: false });
                }
                if (!db.objectStoreNames.contains(KHO_ANH_CHUP)) {
                    db.createObjectStore(KHO_ANH_CHUP, { keyPath: 'khoa' });
                }
            };
            yc.onsuccess = function () { _db = yc.result; ok(_db); };
            yc.onerror = function () { that_bai(yc.error); };
        });
    }

    function chay(ten_kho, che_do, viec) {
        return moDB().then(function (db) {
            return new Promise(function (ok, that_bai) {
                const tx = db.transaction(ten_kho, che_do);
                const kq = viec(tx.objectStore(ten_kho));
                tx.oncomplete = function () { ok(kq && kq.result !== undefined ? kq.result : kq); };
                tx.onerror = function () { that_bai(tx.error); };
                tx.onabort = function () { that_bai(tx.error); };
            });
        });
    }

    function dangOffline() {
        return navigator.onLine === false;
    }

    // ---------- Hàng chờ ----------
    function taoUuid() {
        if (global.crypto && crypto.randomUUID) return 'off-' + crypto.randomUUID();
        return 'off-' + Date.now() + '-' + Math.random().toString(16).slice(2, 10);
    }

    /** Lưu một phiếu đã bán. `items` lấy thẳng từ giỏ hàng của POS. */
    function luuPhieu(shopId, gio_hang, tien_khach_dua, ten_may) {
        const phieu = {
            offline_uuid: taoUuid(),
            shop_id: Number(shopId),
            sold_at: new Date().toISOString(),
            items: (gio_hang || []).map(function (m) {
                return {
                    product_id: Number(m.product_id),
                    product_name: String(m.product_name || ''),
                    // Giá LÚC BÁN. Server tôn trọng con số này chứ không tính
                    // lại theo giá hôm nay - xem bẫy 28 trong KIEN_TRUC.md.
                    unit_price: Number(m.price) || 0,
                    quantity: Number(m.quantity) || 0
                };
            }),
            cash_tendered: Number(tien_khach_dua) || 0,
            device_label: ten_may || null,
            luc_luu: Date.now(),
            loi: null
        };
        return chay(KHO_PHIEU, 'readwrite', function (kho) { kho.put(phieu); })
            .then(function () { return phieu; });
    }

    function docTatCa(shopId) {
        return chay(KHO_PHIEU, 'readonly', function (kho) { return kho.getAll(); })
            .then(function (ds) {
                return (ds || []).filter(function (p) {
                    return !shopId || Number(p.shop_id) === Number(shopId);
                });
            });
    }

    /** Số phiếu CHỜ GỬI. Phiếu đã đánh dấu lỗi không tính vào đây - nó cần
     *  người xử lý chứ không phải chờ mạng. */
    function demCho(shopId) {
        return docTatCa(shopId).then(function (ds) {
            return ds.filter(function (p) { return !p.loi; }).length;
        });
    }

    function demLoi(shopId) {
        return docTatCa(shopId).then(function (ds) {
            return ds.filter(function (p) { return !!p.loi; }).length;
        });
    }

    function xoaPhieu(uuid) {
        return chay(KHO_PHIEU, 'readwrite', function (kho) { kho.delete(uuid); });
    }

    function danhDauLoi(phieu, ly_do) {
        phieu.loi = String(ly_do || 'không rõ').slice(0, 300);
        return chay(KHO_PHIEU, 'readwrite', function (kho) { kho.put(phieu); });
    }

    let _dangDongBo = false;

    /** Gửi mọi phiếu đang chờ. Trả về {da_gui, loi, con_lai}. */
    async function dongBo(shopId) {
        if (_dangDongBo || dangOffline()) return { da_gui: 0, loi: 0, con_lai: await demCho(shopId) };
        _dangDongBo = true;
        let da_gui = 0, loi = 0;
        try {
            const ds = (await docTatCa(shopId)).filter(function (p) { return !p.loi; });
            // Cũ trước mới sau: đơn lên server theo đúng thứ tự đã bán.
            ds.sort(function (a, b) { return (a.luc_luu || 0) - (b.luc_luu || 0); });

            for (const phieu of ds) {
                try {
                    await apiCall(`/orders/${phieu.shop_id}/offline`, 'POST', {
                        offline_uuid: phieu.offline_uuid,
                        sold_at: phieu.sold_at,
                        items: phieu.items,
                        cash_tendered: phieu.cash_tendered,
                        device_label: phieu.device_label
                    });
                    // Cả `created: true` lẫn `false` đều nghĩa là ĐÃ ghi trên
                    // server. `false` chỉ là lần gửi lại của một phiếu đã vào sổ.
                    await xoaPhieu(phieu.offline_uuid);
                    da_gui += 1;
                } catch (e) {
                    const ma = Number(e && e.status);
                    if (ma >= 400 && ma < 500) {
                        // Sẽ không bao giờ gửi được. Giữ lại làm bằng chứng, đánh
                        // dấu để không thử lại vô hạn và không chặn phiếu sau.
                        await danhDauLoi(phieu, `${ma}: ${e.message || ''}`);
                        loi += 1;
                        continue;
                    }
                    // Mạng lại hỏng giữa chừng: dừng hẳn, giữ nguyên phần còn lại.
                    break;
                }
            }
        } finally {
            _dangDongBo = false;
        }
        return { da_gui, loi, con_lai: await demCho(shopId) };
    }

    // ---------- Ảnh chụp danh mục ----------
    // Mất mạng thì `GET /api/products` hỏng. Không có bản chụp thì màn POS trống
    // trơn và không bán được gì - hàng chờ có cũng vô nghĩa.
    function luuAnhChupSanPham(shopId, danh_sach) {
        return chay(KHO_ANH_CHUP, 'readwrite', function (kho) {
            kho.put({ khoa: 'sp:' + shopId, luc: Date.now(), du_lieu: danh_sach || [] });
        });
    }

    function docAnhChupSanPham(shopId) {
        return chay(KHO_ANH_CHUP, 'readonly', function (kho) {
            return kho.get('sp:' + shopId);
        }).then(function (b) { return b ? b.du_lieu : null; });
    }

    // ---------- Tự đồng bộ ----------
    /** Gọi một lần lúc POS khởi động. `khiXong(kq)` chạy sau mỗi lượt đồng bộ. */
    function batTuDongBo(layShopId, khiXong) {
        async function thu() {
            const shopId = layShopId();
            if (!shopId || dangOffline()) return;
            try {
                const kq = await dongBo(shopId);
                if (khiXong) khiXong(kq);
            } catch (e) {
                console.warn('[OFFLINE] Đồng bộ thất bại:', e);
            }
        }
        global.addEventListener('online', thu);
        // Thử luôn lúc nạp trang: máy có thể đã online từ trước khi mở POS, khi
        // đó sự kiện 'online' không bao giờ bắn.
        setTimeout(thu, 1500);
        return thu;
    }

    global.OfflineBan = {
        dangOffline,
        luuPhieu,
        docTatCa,
        demCho,
        demLoi,
        xoaPhieu,
        dongBo,
        luuAnhChupSanPham,
        docAnhChupSanPham,
        batTuDongBo
    };
})(window);
