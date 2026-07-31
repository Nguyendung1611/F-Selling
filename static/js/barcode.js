/**
 * Lớp quét mã vạch dùng chung cho POS, Kho hàng và form sản phẩm.
 *
 * Nguồn quét hiện tại là máy quét cầm tay cắm USB. Với máy tính, loại máy này
 * KHÔNG phải thiết bị đặc biệt: nó giả làm bàn phím, "gõ" cả chuỗi mã rồi kết
 * thúc bằng Enter (một số máy đặt là Tab). Vì vậy không cần thư viện, không cần
 * quyền truy cập thiết bị, và cũng không cần HTTPS.
 *
 * Phân biệt máy quét với người gõ tay bằng tốc độ: máy quét bắn ra mỗi ký tự
 * cách nhau khoảng 5-20ms, người gõ nhanh nhất cũng hiếm khi dưới 80ms. Nhờ đó
 * bắt được ở tầm `document` mà không cần con trỏ nằm trong ô nhập nào - thu ngân
 * đang chọn khách hàng vẫn quét được hàng vào giỏ.
 *
 * Giai đoạn sau sẽ thêm nguồn quét bằng camera điện thoại; nó chỉ việc gọi
 * `BarcodeScanner.xuLy(code)` nên phần dưới đây không phải sửa gì.
 */
(function (global) {
    'use strict';

    function dich(key, vi, en) {
        const locale = global.getCurrentLocale?.() || 'vi';
        const defaultValue = locale === 'en' ? en : vi;
        return global.t ? global.t(key, { defaultValue }) : defaultValue;
    }

    // Khoảng cách tối đa giữa hai phím để còn được coi là cùng một lượt quét.
    // 50ms nằm giữa hai vùng an toàn: máy quét (5-20ms) và người gõ (>80ms).
    const NGUONG_MS = 50;

    // Mã ngắn hơn mức này gần như chắc chắn là người gõ tay rồi bấm Enter.
    const DAI_TOI_THIEU = 4;

    let dem = '';              // ký tự đã gom của lượt quét đang diễn ra
    let mocThoiGian = 0;       // thời điểm phím trước đó
    let oDangNhap = null;      // ô nhập đang focus lúc bắt đầu lượt quét
    let giaTriTruoc = '';      // giá trị của ô đó, để hoàn nguyên nếu là lượt quét
    let xuLyHienTai = null;    // handler do trang hiện tại đăng ký
    let audioCtx = null;

    function laONhap(el) {
        if (!el) return false;
        const tag = el.tagName;
        return tag === 'INPUT' || tag === 'TEXTAREA' || el.isContentEditable;
    }

    function datLai() {
        dem = '';
        oDangNhap = null;
        giaTriTruoc = '';
    }

    /**
     * Chuẩn hóa giống hệt `normalize_barcode` ở backend (catalog_service.py):
     * bỏ khoảng trắng, viết hoa. Hai bên lệch nhau là quét không ra sản phẩm.
     */
    function chuanHoa(raw) {
        if (raw === null || raw === undefined) return '';
        return String(raw).replace(/\s+/g, '').toUpperCase();
    }

    // ----- Âm báo -----
    // Thu ngân không nhìn màn hình khi quét, nên tiếng bíp là kênh phản hồi
    // chính. Bíp cao ngắn = xong; bíp trầm dài = có vấn đề, phải ngẩng lên nhìn.
    function keu(tanSo, giay) {
        try {
            const Ctx = global.AudioContext || global.webkitAudioContext;
            if (!Ctx) return;
            if (!audioCtx) audioCtx = new Ctx();
            // Trình duyệt treo AudioContext cho tới khi người dùng tương tác.
            if (audioCtx.state === 'suspended') audioCtx.resume();

            const osc = audioCtx.createOscillator();
            const gain = audioCtx.createGain();
            osc.type = 'square';
            osc.frequency.value = tanSo;
            // Vào/ra êm để không bị tiếng "tạch" ở hai đầu.
            gain.gain.setValueAtTime(0.0001, audioCtx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.12, audioCtx.currentTime + 0.01);
            gain.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + giay);
            osc.connect(gain);
            gain.connect(audioCtx.destination);
            osc.start();
            osc.stop(audioCtx.currentTime + giay);
        } catch (e) {
            // Không có tiếng thì thôi, không được để vỡ luồng bán hàng.
        }
    }

    function bipOk() { keu(1180, 0.07); }
    function bipLoi() { keu(220, 0.28); }

    /** Đưa một mã vào handler của trang. Dùng chung cho máy quét và camera. */
    function xuLy(ma) {
        const sach = chuanHoa(ma);
        if (!sach || !xuLyHienTai) return;
        try {
            xuLyHienTai(sach);
        } catch (e) {
            console.error(dich(
                'barcode.scanner.handle_error',
                'Lỗi xử lý mã vạch:',
                'Barcode handling error:'
            ), e);
            bipLoi();
        }
    }

    function khiNhanPhim(e) {
        // Ctrl/Alt/Meta = phím tắt của người dùng, máy quét không gửi các phím này.
        if (e.ctrlKey || e.altKey || e.metaKey) return datLai();
        // Một số trình duyệt/công cụ hỗ trợ có thể phát sự kiện bàn phím tổng hợp
        // không kèm `key`. Bỏ qua sự kiện đó thay vì làm gián đoạn trang POS.
        if (typeof e.key !== 'string') return datLai();

        const bayGio = Date.now();
        const cachNhau = bayGio - mocThoiGian;
        mocThoiGian = bayGio;

        // Gõ chậm -> bắt đầu lại từ đầu. Nhờ vậy người gõ tay không bao giờ tích
        // đủ DAI_TOI_THIEU ký tự: mỗi phím chậm lại đưa bộ đếm về 1.
        if (cachNhau > NGUONG_MS) {
            datLai();
            oDangNhap = laONhap(document.activeElement) ? document.activeElement : null;
            giaTriTruoc = oDangNhap ? oDangNhap.value : '';
        }

        // Máy quét kết thúc bằng Enter, một số model cấu hình sẵn là Tab.
        if (e.key === 'Enter' || e.key === 'Tab') {
            if (dem.length >= DAI_TOI_THIEU) {
                const ma = dem;
                // Ký tự của lượt quét đã kịp lọt vào ô đang focus trước khi ta
                // kết luận đây là máy quét. Trả ô về nguyên trạng để mã vạch
                // không dính vào ô tìm kiếm hay ô đang nhập dở.
                if (oDangNhap && oDangNhap.value !== giaTriTruoc) {
                    oDangNhap.value = giaTriTruoc;
                    oDangNhap.dispatchEvent(new Event('input', { bubbles: true }));
                }
                e.preventDefault();
                datLai();
                xuLy(ma);
                return;
            }
            datLai();
            return;
        }

        // Chỉ gom ký tự in được; bỏ qua Shift, F1, mũi tên...
        if (e.key.length === 1) dem += e.key;
    }

    /**
     * Đăng ký hàm nhận mã cho trang hiện tại. Gọi lại lần nữa sẽ thay handler cũ.
     * Handler nhận vào mã đã chuẩn hóa (viết hoa, không khoảng trắng).
     */
    function dangKy(handler) {
        xuLyHienTai = handler;
    }

    let daGan = false;
    function batDau(handler) {
        if (handler) dangKy(handler);
        if (daGan) return;
        // capture=true để nhận phím trước khi ô nhập kịp xử lý Enter của nó.
        document.addEventListener('keydown', khiNhanPhim, true);
        daGan = true;
    }

    global.BarcodeScanner = {
        batDau: batDau,
        dangKy: dangKy,
        xuLy: xuLy,
        chuanHoa: chuanHoa,
        bipOk: bipOk,
        bipLoi: bipLoi
    };
})(window);
