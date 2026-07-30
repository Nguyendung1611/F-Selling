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
    let phienPhatFile = 0;
    const boNhoFile = new Map();

    /**
     * Danh sách MP3 để đọc "Đã nhận <số tiền> đồng".
     *
     * Bộ file được sinh trước nên máy POS không cần giọng Việt của hệ điều
     * hành và server cũng không cần API key TTS cho thông báo quan trọng này.
     */
    function tepDocSoTien(soTien) {
        const giaTri = Number(soTien);
        if (!Number.isFinite(giaTri) || giaTri < 0) return [];
        const tep = ['/audio/da_nhan.mp3'];
        for (const tu of docSo(giaTri).split(' ')) {
            if (!TEP_TU[tu]) return [];
            tep.push('/audio/' + TEP_TU[tu]);
        }
        tep.push('/audio/dong.mp3');
        return tep;
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
        const tep = tepDocSoTien(soTien);
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
        return noiSoTien(soTien, cauDaNhan(soTien, orderId));
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
        return noiSoTien(150000, cauDaNhan(150000, 42));
    }

    global.DocTien = {
        docSo: docSo,
        tepDocSoTien: tepDocSoTien,
        cauDaNhan: cauDaNhan,
        noi: noi,
        chuanBiSoTien: chuanBiSoTien,
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
