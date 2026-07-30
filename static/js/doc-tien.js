/**
 * Đọc to khi tiền chuyển khoản về, để thu ngân không phải nhìn màn hình.
 *
 * Dùng `SpeechSynthesis` có sẵn trong trình duyệt - không cần dịch vụ trả phí,
 * không cần mạng sau khi trang đã tải.
 *
 * Số tiền được đổi sang CHỮ trước khi đọc ("một trăm năm mươi nghìn") thay vì
 * đưa thẳng chuỗi "150.000". Nhiều bộ đọc gặp dấu chấm ngăn cách nghìn sẽ đọc
 * thành "một trăm năm mươi chấm không không không", hoặc đọc từng chữ số.
 */
(function (global) {
    'use strict';

    const KHOA = {
        bat: 'docTien.bat',
        giong: 'docTien.giong'
    };

    // Server có sinh được giọng Việt không. null = chưa hỏi.
    let serverDocDuoc = null;

    // Đơn đã đọc rồi thì thôi. Polling có thể bắt được cùng một trạng thái hai
    // lần nếu người dùng tải lại trang, không để nó đọc lại lần nữa.
    const daDoc = new Set();

    // ----- Đổi số sang chữ tiếng Việt -----

    const CHU_SO = ['không', 'một', 'hai', 'ba', 'bốn', 'năm', 'sáu', 'bảy', 'tám', 'chín'];
    const NHOM = ['', ' nghìn', ' triệu', ' tỷ'];

    /** Đọc một nhóm dưới 1000. `duTram` = phải đọc cả hàng trăm dù bằng 0. */
    function docBaChuSo(n, duTram) {
        const tram = Math.floor(n / 100);
        const chuc = Math.floor((n % 100) / 10);
        const donVi = n % 10;
        let s = '';

        if (tram > 0 || duTram) s += CHU_SO[tram] + ' trăm';

        if (chuc === 0) {
            if (donVi > 0) s += (tram > 0 || duTram) ? ' lẻ ' + CHU_SO[donVi] : CHU_SO[donVi];
        } else if (chuc === 1) {
            s += ' mười';
            if (donVi === 5) s += ' lăm';          // mười lăm, không phải "mười năm"
            else if (donVi > 0) s += ' ' + CHU_SO[donVi];
        } else {
            s += ' ' + CHU_SO[chuc] + ' mươi';
            if (donVi === 1) s += ' mốt';          // hai mươi mốt
            else if (donVi === 4) s += ' tư';      // hai mươi tư
            else if (donVi === 5) s += ' lăm';     // hai mươi lăm
            else if (donVi > 0) s += ' ' + CHU_SO[donVi];
        }
        return s.trim();
    }

    function docSo(n) {
        n = Math.round(Number(n) || 0);
        if (n === 0) return 'không';
        if (n < 0) return 'âm ' + docSo(-n);

        const nhom = [];
        while (n > 0) {
            nhom.push(n % 1000);
            n = Math.floor(n / 1000);
        }

        const phan = [];
        for (let i = nhom.length - 1; i >= 0; i--) {
            if (nhom[i] === 0) continue;
            // Nhóm cao nhất không cần đọc "không trăm"; các nhóm sau thì cần,
            // nếu không "một triệu không trăm lẻ năm nghìn" sẽ thành
            // "một triệu năm nghìn" - sai hẳn con số.
            phan.push(docBaChuSo(nhom[i], i !== nhom.length - 1) + NHOM[i]);
        }
        return phan.join(' ').replace(/\s+/g, ' ').trim();
    }

    // ----- Cấu hình, lưu trên máy -----

    function dangBat() {
        return localStorage.getItem(KHOA.bat) !== '0';   // mặc định BẬT
    }

    function datBat(bat) {
        localStorage.setItem(KHOA.bat, bat ? '1' : '0');
    }

    function danhSachGiong() {
        if (!global.speechSynthesis) return [];
        return global.speechSynthesis.getVoices() || [];
    }

    function giongTiengViet() {
        return danhSachGiong().filter(v => (v.lang || '').toLowerCase().startsWith('vi'));
    }

    function giongDangChon() {
        const ten = localStorage.getItem(KHOA.giong);
        const tatCa = danhSachGiong();
        if (ten) {
            const khop = tatCa.find(v => v.name === ten);
            if (khop) return khop;
        }
        return giongTiengViet()[0] || null;   // ưu tiên giọng Việt bất kỳ
    }

    // ----- Đọc -----

    /** Đọc bằng giọng cài sẵn trên thiết bị. */
    function noiBangThietBi(cauChu) {
        if (!global.speechSynthesis || !global.SpeechSynthesisUtterance) return false;
        try {
            const u = new global.SpeechSynthesisUtterance(cauChu);
            u.lang = 'vi-VN';
            const giong = giongDangChon();
            if (giong) u.voice = giong;
            // Hủy câu đang đọc dở: bán liên tục thì câu mới quan trọng hơn câu cũ.
            global.speechSynthesis.cancel();
            global.speechSynthesis.speak(u);
            return true;
        } catch (e) {
            console.error('Lỗi đọc tiền:', e);
            return false;
        }
    }

    let tiengDangPhat = null;

    /** Nhờ server sinh giọng Việt rồi phát. Trả về Promise<boolean>. */
    async function noiBangServer(cauChu) {
        try {
            const res = await fetch('/api/tts', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + getToken()
                },
                body: JSON.stringify({ text: cauChu })
            });
            if (!res.ok) {
                serverDocDuoc = false;   // hỏng thì thôi, khỏi thử lại từng lượt
                return false;
            }
            const url = URL.createObjectURL(await res.blob());
            if (tiengDangPhat) { try { tiengDangPhat.pause(); } catch (e) {} }
            tiengDangPhat = new Audio(url);
            tiengDangPhat.onended = () => URL.revokeObjectURL(url);
            await tiengDangPhat.play();
            return true;
        } catch (e) {
            console.error('Lỗi gọi giọng đọc từ server:', e);
            return false;
        }
    }

    /**
     * Đọc một câu. Hai tầng:
     *   1. Thiết bị có giọng tiếng Việt -> đọc ngay tại máy. Nhanh, miễn phí,
     *      không cần mạng.
     *   2. Không có -> nhờ server sinh. Chrome trên Windows rơi vào đây vì bộ
     *      giọng kèm theo Chrome không có tiếng Việt.
     * Cả hai đều không được thì đọc bằng giọng nước ngoài còn hơn im lặng -
     * người bán vẫn nghe thấy CÓ tiếng và biết mà nhìn màn hình.
     */
    function noi(cauChu) {
        if (giongTiengViet().length) return noiBangThietBi(cauChu);
        if (serverDocDuoc !== false) {
            noiBangServer(cauChu).then(ok => { if (!ok) noiBangThietBi(cauChu); });
            return true;
        }
        return noiBangThietBi(cauChu);
    }

    /** Hỏi server một lần xem có sinh được giọng không, để giao diện báo đúng. */
    async function kiemTraServer() {
        try {
            const res = await fetch('/api/tts/status', {
                headers: { 'Authorization': 'Bearer ' + getToken() }
            });
            serverDocDuoc = res.ok ? (await res.json()).enabled === true : false;
        } catch (e) {
            serverDocDuoc = false;
        }
        return serverDocDuoc;
    }

    function cauDaNhan(soTien, orderId) {
        return `Đã nhận ${docSo(soTien)} đồng, đơn hàng số ${docSo(orderId)}.`;
    }

    /** Gọi khi webhook báo đơn đã thanh toán đủ. */
    function thongBaoDaNhan(orderId, soTien) {
        if (!dangBat()) return false;
        const khoa = 'PAID:' + orderId;
        if (daDoc.has(khoa)) return false;
        daDoc.add(khoa);
        return noi(cauDaNhan(soTien, orderId));
    }

    /** Gọi khi đơn rơi vào trạng thái cần đối soát (thường là khách chuyển thiếu). */
    function canhBaoDoiSoat(orderId) {
        if (!dangBat()) return false;
        const khoa = 'UNREC:' + orderId;
        if (daDoc.has(khoa)) return false;
        daDoc.add(khoa);
        return noi(`Chú ý! Đơn hàng số ${docSo(orderId)} cần đối soát. Kiểm tra lại số tiền.`);
    }

    function thuGiong() {
        return noi(cauDaNhan(150000, 42));
    }

    global.DocTien = {
        docSo: docSo,
        cauDaNhan: cauDaNhan,
        noi: noi,
        thongBaoDaNhan: thongBaoDaNhan,
        canhBaoDoiSoat: canhBaoDoiSoat,
        thuGiong: thuGiong,
        dangBat: dangBat,
        datBat: datBat,
        danhSachGiong: danhSachGiong,
        giongTiengViet: giongTiengViet,
        giongDangChon: giongDangChon,
        kiemTraServer: kiemTraServer,
        serverDocDuoc: () => serverDocDuoc,
        KHOA: KHOA
    };
})(window);
