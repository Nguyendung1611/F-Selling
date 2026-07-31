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
        bat: 'docTien.bat'
    };
    const TEP_CANH_BAO_THIEU_TIEN = '/audio/canh_bao_thieu_tien.mp3';
    const TEP_CON_THIEU = '/audio/con_thieu.mp3';
    const TEP_CHUYEN_THUA = '/audio/chuyen_thua.mp3';
    const TEP_CAN_HOAN_LAI = '/audio/can_hoan_lai.mp3';

    // Server có sinh được giọng Việt không. null = chưa hỏi.
    let serverDocDuoc = null;

    // Đơn đã đọc rồi thì thôi. Polling có thể bắt được cùng một trạng thái hai
    // lần nếu người dùng tải lại trang, không để nó đọc lại lần nữa.
    const daDoc = new Set();

    // ----- Đổi số sang chữ tiếng Việt -----

    const CHU_SO = ['không', 'một', 'hai', 'ba', 'bốn', 'năm', 'sáu', 'bảy', 'tám', 'chín'];
    const NHOM = ['', ' nghìn', ' triệu', ' tỷ'];
    const TEP_TU = {
        'không': '0.mp3',
        'một': '1.mp3',
        'hai': '2.mp3',
        'ba': '3.mp3',
        'bốn': '4.mp3',
        'năm': '5.mp3',
        'sáu': '6.mp3',
        'bảy': '7.mp3',
        'tám': '8.mp3',
        'chín': '9.mp3',
        'mười': 'muoi_10.mp3',
        'mươi': 'muoi_tens.mp3',
        'lăm': 'lam.mp3',
        'mốt': 'mot_mot.mp3',
        'tư': 'tu.mp3',
        'lẻ': 'le.mp3',
        'trăm': 'tram.mp3',
        'nghìn': 'nghin.mp3',
        'triệu': 'trieu.mp3',
        'tỷ': 'ty.mp3'
    };

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
        // Không dùng lựa chọn cũ có thể là giọng English. Tầng dự phòng chỉ
        // được phép nói khi máy thật sự có giọng tiếng Việt.
        return giongTiengViet()[0] || null;
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
    let phienPhatFile = 0;
    const boNhoFile = new Map();

    /**
     * Danh sách MP3 để đọc "Đã nhận <số tiền> đồng".
     *
     * Bộ file được sinh trước nên máy POS không cần giọng Việt của hệ điều
     * hành và server cũng không cần API key TTS cho thông báo quan trọng này.
     */
    function tepPhanSoTien(soTien) {
        const giaTri = Number(soTien);
        if (!Number.isFinite(giaTri) || giaTri < 0) return [];
        const tep = [];
        for (const tu of docSo(giaTri).split(' ')) {
            if (!TEP_TU[tu]) return [];
            tep.push('/audio/' + TEP_TU[tu]);
        }
        tep.push('/audio/dong.mp3');
        return tep;
    }

    function tepDocSoTien(soTien) {
        const phanSo = tepPhanSoTien(soTien);
        return phanSo.length ? ['/audio/da_nhan.mp3'].concat(phanSo) : [];
    }

    function tepCanhBaoThieu(received, remaining) {
        const daNhan = tepDocSoTien(received);
        const conThieu = tepPhanSoTien(remaining);
        if (!daNhan.length || !conThieu.length) return [];
        return daNhan.concat([TEP_CON_THIEU], conThieu);
    }

    function tepCanhBaoThua(received, excess) {
        const daNhan = tepDocSoTien(received);
        const tienThua = tepPhanSoTien(excess);
        if (!daNhan.length || !tienThua.length) return [];
        return daNhan.concat([TEP_CHUYEN_THUA], tienThua, [TEP_CAN_HOAN_LAI]);
    }

    /** Nạp một file vào RAM; cùng một từ chỉ tải đúng một lần trong phiên. */
    async function taiTep(url) {
        if (!boNhoFile.has(url)) {
            boNhoFile.set(url, fetch(url).then(async res => {
                if (!res.ok) throw new Error(`Không tải được ${url}`);
                return res.blob();
            }).catch(err => {
                boNhoFile.delete(url);   // lần sau cho phép thử tải lại
                throw err;
            }));
        }
        return boNhoFile.get(url);
    }

    /** Phát lần lượt các từ đã nạp. Lời gọi mới sẽ dừng câu cũ. */
    async function phatChuoiTep(tep) {
        if (!tep.length) return false;
        const phien = ++phienPhatFile;
        if (tiengDangPhat) {
            try { tiengDangPhat.pause(); } catch (e) {}
        }

        try {
            // Nạp song song trước khi nói để giữa các từ không phải chờ mạng.
            const blobs = await Promise.all(tep.map(taiTep));
            for (const blob of blobs) {
                if (phien !== phienPhatFile) return true;
                const url = URL.createObjectURL(blob);
                const audio = new Audio(url);
                tiengDangPhat = audio;
                const daPhat = await new Promise(resolve => {
                    let xong = false;
                    const ketThuc = ok => {
                        if (xong) return;
                        xong = true;
                        URL.revokeObjectURL(url);
                        resolve(ok);
                    };
                    audio.onended = () => ketThuc(true);
                    audio.onerror = () => ketThuc(false);
                    const batDau = audio.play();
                    if (batDau && typeof batDau.catch === 'function') {
                        batDau.catch(() => ketThuc(false));
                    }
                });
                if (!daPhat) return false;
            }
            if (phien === phienPhatFile) tiengDangPhat = null;
            return true;
        } catch (e) {
            console.error('Lỗi phát bộ MP3 đọc tiền:', e);
            return false;
        }
    }

    /** Tải trước đúng các từ của đơn đang chờ để tiền về là đọc ngay. */
    function chuanBiSoTien(soTien) {
        // Một giao dịch đang chờ có thể đủ hoặc thiếu tiền, nên tải sẵn cả
        // câu cảnh báo thiếu tiền ngay từ lúc QR vừa hiện.
        const tep = tepDocSoTien(soTien).concat([
            TEP_CANH_BAO_THIEU_TIEN,
            TEP_CON_THIEU,
            TEP_CHUYEN_THUA,
            TEP_CAN_HOAN_LAI
        ]);
        return Promise.all(tep.map(taiTep)).then(() => true).catch(() => false);
    }

    /** Ưu tiên bộ MP3 có sẵn; hỏng file mới lùi về TTS cũ. */
    function noiSoTien(soTien, cauDuPhong) {
        phatChuoiTep(tepDocSoTien(soTien)).then(ok => {
            if (!ok) noi(cauDuPhong);
        });
        return true;
    }

    /** Nhờ server sinh giọng Việt rồi phát. Trả về Promise<boolean>. */
    async function noiBangServer(cauChu) {
        try {
            const res = await fetch('/api/tts', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + getToken(),
                    'Accept-Language': getCurrentLocale()
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
     * Tầng dự phòng CHỈ dùng giọng tiếng Việt: giọng Việt của thiết bị hoặc
     * server TTS. Không bao giờ lùi về Microsoft David/giọng English.
     */
    function noi(cauChu) {
        if (giongTiengViet().length) return noiBangThietBi(cauChu);
        if (serverDocDuoc !== false) {
            noiBangServer(cauChu);
            return true;
        }
        return false;
    }

    /** Hỏi server một lần xem có sinh được giọng không, để giao diện báo đúng. */
    async function kiemTraServer() {
        try {
            const res = await fetch('/api/tts/status', {
                headers: {
                    'Authorization': 'Bearer ' + getToken(),
                    'Accept-Language': getCurrentLocale()
                }
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
        return noiSoTien(soTien, cauDaNhan(soTien, orderId));
    }

    /** Đọc mỗi lần tổng thực nhận đổi: "Đã nhận X, còn thiếu Y". */
    function canhBaoThieuTien(orderId, received, remaining) {
        if (!dangBat()) return false;
        const khoa = `UNDER:${orderId}:${Math.round(Number(received) || 0)}`;
        if (daDoc.has(khoa)) return false;
        daDoc.add(khoa);
        const cauDuPhong = `Đã nhận ${docSo(received)} đồng. Còn thiếu ${docSo(remaining)} đồng.`;
        const tep = tepCanhBaoThieu(received, remaining);
        phatChuoiTep(tep).then(ok => {
            if (!ok) noi(cauDuPhong);
        });
        return true;
    }

    /** Đơn vẫn PAID/xuất hóa đơn, nhưng thu ngân phải biết số cần hoàn. */
    function canhBaoThuaTien(orderId, received, excess) {
        if (!dangBat()) return false;
        const khoa = `OVER:${orderId}:${Math.round(Number(received) || 0)}`;
        if (daDoc.has(khoa)) return false;
        daDoc.add(khoa);
        const cauDuPhong = `Đã nhận ${docSo(received)} đồng. Chuyển thừa ${docSo(excess)} đồng. Cần hoàn lại.`;
        phatChuoiTep(tepCanhBaoThua(received, excess)).then(ok => {
            if (!ok) noi(cauDuPhong);
        });
        return true;
    }

    /** Tương thích trang cũ đang cache: cảnh báo chung vẫn hoàn toàn tiếng Việt. */
    function canhBaoDoiSoat(orderId) {
        return canhBaoThieuTien(orderId, 0, 0);
    }

    function thuDuTien() {
        return noiSoTien(150000, cauDaNhan(150000, 42));
    }

    function thuThieuTien() {
        return phatChuoiTep(tepCanhBaoThieu(50000, 100000));
    }

    function thuThuaTien() {
        return phatChuoiTep(tepCanhBaoThua(170000, 20000));
    }

    global.DocTien = {
        docSo: docSo,
        tepDocSoTien: tepDocSoTien,
        cauDaNhan: cauDaNhan,
        noi: noi,
        chuanBiSoTien: chuanBiSoTien,
        thongBaoDaNhan: thongBaoDaNhan,
        canhBaoThieuTien: canhBaoThieuTien,
        canhBaoThuaTien: canhBaoThuaTien,
        canhBaoDoiSoat: canhBaoDoiSoat,
        thuGiong: thuDuTien,   // tương thích nút cũ nếu trang còn cache
        thuDuTien: thuDuTien,
        thuThieuTien: thuThieuTien,
        thuThuaTien: thuThuaTien,
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
