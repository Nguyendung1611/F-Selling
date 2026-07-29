/**
 * Quét mã vạch bằng camera điện thoại. Nguồn quét thứ hai bên cạnh máy quét USB.
 *
 * Mã đọc được đi vào đúng `BarcodeScanner.xuLy()` mà máy quét USB đang dùng, nên
 * trang nào đã đăng ký handler là tự động quét được bằng camera, không phải sửa
 * gì thêm.
 *
 * Hai bộ giải mã:
 *   1. `BarcodeDetector` có sẵn trong trình duyệt (Chrome/Edge trên Android và
 *      máy tính). Nhanh, không tải gì thêm.
 *   2. Thư viện ZXing tải từ CDN, dùng khi trình duyệt không có sẵn - chủ yếu là
 *      Safari trên iPhone/iPad.
 *
 * BẮT BUỘC HTTPS: trình duyệt chỉ cho truy cập camera trên trang https (hoặc
 * localhost). Mở app qua http://192.168.x.x trên điện thoại sẽ KHÔNG quét được
 * bằng camera - phải chạy qua ngrok hoặc bản đã deploy. Trường hợp này được
 * phát hiện và báo rõ ràng thay vì để lỗi khó hiểu.
 */
(function (global) {
    'use strict';

    const ZXING_CDN = 'https://unpkg.com/@zxing/library@0.21.3/umd/index.min.js';

    // Cùng một mã nằm trong khung ngắm sẽ được đọc lại ở MỌI khung hình. Nếu chỉ
    // chờ hết một khoảng thời gian rồi nhận lại, người bán để yên máy vài giây là
    // món hàng bị cộng thêm mấy lần - tính thừa tiền mà không ai để ý.
    //
    // Nên điều kiện để nhận lại cùng một mã là nó phải RỜI KHỎI KHUNG: chỉ khi
    // khoảng cách giữa hai lần đọc thấy vượt ngưỡng này (tức là đã có quãng
    // không đọc được nó nữa) mới tính là lượt quét mới. Giữ yên trong khung thì
    // các lần đọc cách nhau ~100-300ms nên không bao giờ vượt ngưỡng.
    const NGUONG_ROI_KHUNG_MS = 900;

    // 10 khung hình/giây là quá đủ để bắt mã, mà đỡ tốn pin hơn nhiều so với
    // chạy hết tốc độ màn hình.
    const NHIP_QUET_MS = 100;

    const DINH_DANG = [
        'ean_13', 'ean_8', 'upc_a', 'upc_e',
        'code_128', 'code_39', 'code_93', 'itf', 'codabar', 'qr_code'
    ];

    let modal = null;
    let video = null;
    let dongTrangThai = null;
    let stream = null;
    let dangChay = false;
    let hgnAnimation = null;
    let zxingReader = null;
    let maCuoi = '';
    let lanThayCuoi = 0;
    let dongSauKhiQuet = false;
    let xuLyRieng = null;

    // ----- Dựng giao diện (tự tạo, để hai trang không phải chép HTML) -----

    function dungModal() {
        if (modal) return;

        const style = document.createElement('style');
        style.textContent = `
            #bcCamModal { position: fixed; inset: 0; z-index: 10000; display: none;
                background: rgba(15,23,42,0.92); align-items: center; justify-content: center; }
            #bcCamHop { width: min(92vw, 440px); background: #0F172A; border-radius: 14px;
                border: 1px solid #334155; overflow: hidden; }
            #bcCamKhung { position: relative; background: #000; aspect-ratio: 4/3; }
            #bcCamVideo { width: 100%; height: 100%; object-fit: cover; display: block; }
            #bcCamNgam { position: absolute; inset: 18% 10%; border: 3px solid #38BDF8;
                border-radius: 10px; box-shadow: 0 0 0 100vmax rgba(0,0,0,0.28); }
            #bcCamDuoi { padding: 0.9rem 1rem 1rem; }
            #bcCamTrangThai { color: #CBD5E1; font-size: 0.88rem; min-height: 2.6em;
                margin-bottom: 0.75rem; line-height: 1.45; }
            #bcCamDong { width: 100%; padding: 0.65rem; border-radius: 8px; cursor: pointer;
                border: 1px solid #334155; background: #1E293B; color: #F8FAFC; font-weight: 600; }
        `;
        document.head.appendChild(style);

        modal = document.createElement('div');
        modal.id = 'bcCamModal';
        modal.innerHTML = `
            <div id="bcCamHop">
                <div id="bcCamKhung">
                    <video id="bcCamVideo" playsinline muted></video>
                    <div id="bcCamNgam"></div>
                </div>
                <div id="bcCamDuoi">
                    <div id="bcCamTrangThai">Đang mở camera...</div>
                    <button id="bcCamDong" type="button">Đóng</button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);

        video = modal.querySelector('#bcCamVideo');
        dongTrangThai = modal.querySelector('#bcCamTrangThai');
        modal.querySelector('#bcCamDong').addEventListener('click', dong);
        // Bấm ra ngoài hộp cũng đóng, nhưng bấm trong hộp thì không.
        modal.addEventListener('click', e => { if (e.target === modal) dong(); });
    }

    function bao(text) {
        if (dongTrangThai) dongTrangThai.innerText = text;
    }

    // ----- Tải ZXing khi cần -----

    let zxingDangTai = null;
    function taiZXing() {
        if (global.ZXing) return Promise.resolve(global.ZXing);
        if (zxingDangTai) return zxingDangTai;
        zxingDangTai = new Promise((ok, loi) => {
            const s = document.createElement('script');
            s.src = ZXING_CDN;
            s.onload = () => global.ZXing ? ok(global.ZXing) : loi(new Error('ZXing nạp lỗi'));
            s.onerror = () => loi(new Error('Không tải được thư viện quét'));
            document.head.appendChild(s);
        });
        return zxingDangTai;
    }

    // ----- Xử lý mã đọc được -----

    function nhanMa(raw) {
        const ma = BarcodeScanner.chuanHoa(raw);
        if (!ma) return;

        const bayGio = Date.now();
        const vanConTrongKhung = (ma === maCuoi) && (bayGio - lanThayCuoi < NGUONG_ROI_KHUNG_MS);
        // Cập nhật mốc ở MỌI lần đọc thấy, kể cả lần bị bỏ qua: có vậy mã nằm
        // yên trong khung mới không bao giờ tích đủ khoảng trống để được nhận lại.
        maCuoi = ma;
        lanThayCuoi = bayGio;
        if (vanConTrongKhung) return;

        // `xuLyRieng` được đọc ra trước khi đóng, vì `dong()` xóa nó đi.
        const xuLy = xuLyRieng || BarcodeScanner.xuLy;

        if (dongSauKhiQuet) {
            dong();
            xuLy(ma);
            return;
        }
        bao(`Đã quét: ${ma}`);
        xuLy(ma);
    }

    // ----- Hai đường giải mã -----

    async function chayBarcodeDetector() {
        let hoTro = [];
        try {
            hoTro = await global.BarcodeDetector.getSupportedFormats();
        } catch (e) { /* không hỏi được thì cứ dùng danh sách mặc định */ }

        const dinhDang = DINH_DANG.filter(f => !hoTro.length || hoTro.includes(f));
        const detector = new global.BarcodeDetector(
            dinhDang.length ? { formats: dinhDang } : undefined
        );

        bao('Đưa mã vạch vào khung. Giữ máy cách khoảng 15-20cm.');

        let lanTruoc = 0;
        const vongLap = async (mocThoiGian) => {
            if (!dangChay) return;
            hgnAnimation = requestAnimationFrame(vongLap);
            if (mocThoiGian - lanTruoc < NHIP_QUET_MS) return;
            lanTruoc = mocThoiGian;
            try {
                const ketQua = await detector.detect(video);
                if (ketQua && ketQua.length) nhanMa(ketQua[0].rawValue);
            } catch (e) {
                // Khung hình chưa sẵn sàng hoặc không có mã - bình thường, bỏ qua.
            }
        };
        hgnAnimation = requestAnimationFrame(vongLap);
    }

    async function chayZXing(stream) {
        bao('Đang tải bộ giải mã...');
        const ZXing = await taiZXing();
        zxingReader = new ZXing.BrowserMultiFormatReader();
        bao('Đưa mã vạch vào khung. Giữ máy cách khoảng 15-20cm.');

        // PHẢI dùng decodeFromStream và để ZXing tự gắn stream rồi tự phát hình.
        // Hàm decodeFromVideoElementContinuously chờ sự kiện 'canplay'; nếu mình
        // đã gọi video.play() trước thì sự kiện đó bắn xong rồi, ZXing chờ mãi
        // và không bao giờ bắt đầu giải mã - camera hiện hình nhưng quét không ra.
        zxingReader.decodeFromStream(stream, video, (ketQua) => {
            // Tham số lỗi là NotFoundException ở gần như mọi khung hình
            // (nghĩa là "khung này không có mã") nên cố tình không đụng tới.
            if (ketQua) nhanMa(ketQua.getText());
        });
    }

    // ----- Mở / đóng -----

    function loiCameraDeHieu(e) {
        const ten = e && e.name;
        if (ten === 'NotAllowedError' || ten === 'SecurityError') {
            return 'Bạn đã từ chối quyền dùng camera. Vào phần cài đặt quyền của trình duyệt để bật lại.';
        }
        if (ten === 'NotFoundError' || ten === 'OverconstrainedError') {
            return 'Không tìm thấy camera trên thiết bị này.';
        }
        if (ten === 'NotReadableError') {
            return 'Camera đang được ứng dụng khác sử dụng. Hãy đóng ứng dụng đó rồi thử lại.';
        }
        return 'Không mở được camera: ' + (e && e.message ? e.message : 'lỗi không rõ');
    }

    /**
     * Mở khung quét.
     *   `dongSauKhiQuet` - đóng ngay sau mã đầu tiên. Dùng khi mã dẫn tới một
     *      hộp thoại khác (nhập/xuất kho); để mở khi cần quét liên tiếp (POS).
     *   `xuLy` - hàm nhận mã cho riêng lần mở này, thay cho handler chung của
     *      trang. Cần khi camera lấy mất focus nên không suy ra được ý định,
     *      ví dụ nút quét nằm cạnh ô mã vạch trong form sản phẩm.
     */
    async function mo(tuyChon) {
        dongSauKhiQuet = !!(tuyChon && tuyChon.dongSauKhiQuet);
        xuLyRieng = (tuyChon && typeof tuyChon.xuLy === 'function') ? tuyChon.xuLy : null;
        dungModal();
        modal.style.display = 'flex';
        maCuoi = '';

        // Kiểm trước hai điều kiện hay hỏng nhất, để báo đúng nguyên nhân thay
        // vì để getUserMedia ném ra lỗi khó hiểu.
        if (!global.isSecureContext) {
            bao('Trình duyệt chỉ cho dùng camera trên kết nối HTTPS. '
                + 'Hãy mở app qua địa chỉ https (ngrok hoặc bản đã deploy), '
                + 'hoặc dùng máy quét USB.');
            return;
        }
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            bao('Trình duyệt này không hỗ trợ truy cập camera. Hãy dùng máy quét USB.');
            return;
        }

        try {
            stream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: 'environment' },  // camera sau
                audio: false
            });
        } catch (e) {
            bao(loiCameraDeHieu(e));
            return;
        }

        dangChay = true;
        try {
            if ('BarcodeDetector' in global) {
                // Đường này tự đọc khung hình nên phải tự phát video.
                video.srcObject = stream;
                await video.play();
                await chayBarcodeDetector();
            } else {
                await chayZXing(stream);
            }
        } catch (e) {
            bao((e && e.message ? e.message : 'Lỗi bộ giải mã')
                + '. Nếu đang không có mạng, hãy dùng máy quét USB.');
            dangChay = false;
        }
    }

    function dong() {
        dangChay = false;
        // Xóa handler riêng để lần mở sau không vô tình dùng lại ý định cũ.
        xuLyRieng = null;

        if (hgnAnimation) { cancelAnimationFrame(hgnAnimation); hgnAnimation = null; }
        if (zxingReader) {
            try { zxingReader.reset(); } catch (e) { /* đóng được tới đâu hay tới đó */ }
            zxingReader = null;
        }
        // Bắt buộc phải tắt từng track, nếu không đèn camera vẫn sáng và máy vẫn
        // tốn pin sau khi đóng hộp thoại.
        if (stream) {
            stream.getTracks().forEach(t => { try { t.stop(); } catch (e) {} });
            stream = null;
        }
        if (video) video.srcObject = null;
        if (modal) modal.style.display = 'none';
    }

    global.BarcodeCamera = { mo: mo, dong: dong };
})(window);
