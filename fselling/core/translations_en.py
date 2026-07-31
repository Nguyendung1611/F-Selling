"""English message catalog for backend responses, email and exported files.

Vietnamese source text is the message id. This mirrors gettext conventions:
the existing Vietnamese contract remains the fallback when a key is missing.
"""

EN_MESSAGES = {
    # Authentication and authorization
    "Phiên đăng nhập không hợp lệ": "Invalid session",
    "Không tìm thấy người dùng": "User not found",
    "Tài khoản đã ngừng hoạt động": "This account has been deactivated",
    "Tài khoản đã được đăng nhập ở thiết bị khác. Vui lòng đăng nhập lại.": (
        "This account was signed in on another device. Please sign in again."
    ),
    "Chỉ quản trị viên được thực hiện thao tác này": (
        "Only administrators can perform this action"
    ),
    "Vai trò nhân viên không có quyền thực hiện thao tác này": (
        "Your staff role does not have permission to perform this action"
    ),
    "Không tìm thấy cửa hàng": "Store not found",
    "Bạn không có quyền truy cập cửa hàng này": (
        "You do not have permission to access this store"
    ),
    "Mật khẩu phải bao gồm kí tự đặc biệt, chữ hoa, chữ thường và số": (
        "Password must include an uppercase letter, a lowercase letter, a number, "
        "and a special character"
    ),
    "Tên đăng nhập đã tồn tại": "Username already exists",
    "Email này đã được đăng ký tài khoản khác": (
        "This email address is already registered to another account"
    ),
    "Đăng ký thành công. Vui lòng kiểm tra email để nhận mã kích hoạt tài khoản.": (
        "Registration successful. Check your email for the account activation code."
    ),
    "Không tìm thấy tài khoản với email này": (
        "No account was found for this email address"
    ),
    "Tài khoản đã được xác minh trước đó.": "This account has already been verified.",
    "Mã xác thực không hợp lệ": "Invalid verification code",
    "Mã xác thực đã hết hạn. Vui lòng đăng ký lại để nhận mã mới.": (
        "The verification code has expired. Register again to receive a new code."
    ),
    "Xác minh tài khoản thành công! Bây giờ bạn đã có thể đăng nhập.": (
        "Account verified successfully! You can now sign in."
    ),
    "Tài khoản đã được xác minh": "This account has already been verified",
    "Đã gửi lại mã xác minh mới vào email của bạn.": (
        "A new verification code has been sent to your email."
    ),
    "Không tìm thấy tài khoản liên kết với email này": (
        "No account is linked to this email address"
    ),
    "Đã gửi mã xác minh khôi phục mật khẩu vào email của bạn.": (
        "A password recovery code has been sent to your email."
    ),
    "Mã xác nhận không hợp lệ": "Invalid confirmation code",
    "Mã xác nhận đã hết hạn": "The confirmation code has expired",
    "Đặt lại mật khẩu thành công! Vui lòng đăng nhập lại.": (
        "Password reset successfully! Please sign in again."
    ),
    "Mật khẩu hiện tại không chính xác": "The current password is incorrect",
    "Mật khẩu mới phải bao gồm kí tự đặc biệt, chữ hoa, chữ thường và số": (
        "The new password must include an uppercase letter, a lowercase letter, "
        "a number, and a special character"
    ),
    "Tên đăng nhập hoặc mật khẩu không chính xác": "Incorrect username or password",
    "Tài khoản chưa được xác minh email. Vui lòng xác minh trước khi đăng nhập.": (
        "Your email has not been verified. Verify it before signing in."
    ),
    "Trường này là bắt buộc": "This field is required",
    "Giá trị phải lớn hơn {minimum}": "The value must be greater than {minimum}",
    "Giá trị phải lớn hơn hoặc bằng {minimum}": (
        "The value must be greater than or equal to {minimum}"
    ),
    "Giá trị phải nhỏ hơn {maximum}": "The value must be less than {maximum}",
    "Giá trị phải nhỏ hơn hoặc bằng {maximum}": (
        "The value must be less than or equal to {maximum}"
    ),
    "Nội dung phải có ít nhất {minimum} ký tự": (
        "The value must contain at least {minimum} characters"
    ),
    "Nội dung chỉ được tối đa {maximum} ký tự": (
        "The value must contain at most {maximum} characters"
    ),
    "Giá trị không nằm trong danh sách được phép": (
        "The value is not one of the permitted choices"
    ),
    "Dữ liệu không hợp lệ. Vui lòng kiểm tra lại": (
        "Invalid input. Check the information and try again"
    ),

    # Stores, staff and customers
    "Tên cửa hàng không được để trống": "Store name is required",
    "Địa chỉ kinh doanh không được để trống": "Business address is required",
    "Mã số thuế không được để trống": "Tax ID is required",
    "Số điện thoại không được để trống": "Phone number is required",
    "Email không được để trống": "Email address is required",
    "Vui lòng chọn ngân hàng": "Select a bank",
    "Số tài khoản không được để trống": "Bank account number is required",
    "Tên chủ tài khoản không được để trống": "Account holder name is required",
    "Nhân viên không được tạo cửa hàng": "Staff members cannot create stores",
    "Bạn chỉ được tạo tối đa {count} cửa hàng": (
        "You can create up to {count} stores"
    ),
    "Tên khách hàng không được để trống": "Customer name is required",
    "Số điện thoại này đã có trong danh sách khách hàng": (
        "This phone number is already in the customer list"
    ),
    "Không tìm thấy khách hàng": "Customer not found",
    "Tên đăng nhập không được để trống": "Username is required",
    "Không tìm thấy nhân viên": "Staff member not found",
    "Nhân viên còn ca đang mở; hãy kết ca trước khi ngừng tài khoản": (
        "This staff member still has an open shift. Close it before deactivating "
        "the account."
    ),
    "Đã đặt lại mật khẩu nhân viên": "Staff password has been reset",

    # Products and orders
    "Dòng hàng phải có product_id hoặc product_name": (
        "Each order item must include product_id or product_name"
    ),
    "Số lượng sản phẩm không hợp lệ": "Invalid product quantity",
    "Sản phẩm {label} không tồn tại hoặc đã ẩn": (
        "Product {label} does not exist or is hidden"
    ),
    "Sản phẩm '{name}' không đủ tồn kho": (
        "There is not enough stock for product '{name}'"
    ),

    # Vouchers
    "Mã voucher không được để trống": "Voucher code is required",
    "Giá trị giảm tối thiểu phải là 1": "Discount value must be at least 1",
    "Giá trị giảm phần trăm phải từ 1% đến 100%": (
        "Percentage discount must be between 1% and 100%"
    ),
    "Đơn tối thiểu không được âm": "Minimum order value cannot be negative",
    "Mã voucher này đã tồn tại trong cửa hàng": (
        "This voucher code already exists in the store"
    ),
    "Voucher không tồn tại": "Voucher not found",
    "Không có quyền chỉnh sửa voucher của cửa hàng này": (
        "You do not have permission to edit this store's voucher"
    ),
    "Mã giảm giá không tồn tại": "Discount code not found",
    "Đơn hàng phải từ {amount} ₫ để áp dụng": (
        "The order total must be at least {amount} VND to use this discount"
    ),
    "Mã giảm giá đã hết lượt sử dụng": "This discount has reached its usage limit",
    "Mã giảm giá đã hết hạn sử dụng": "This discount has expired",

    # Catalog and inventory
    "Mã vạch chỉ gồm chữ, số và dấu gạch ngang, dài 4-64 ký tự": (
        "Barcode must contain only letters, numbers, and hyphens, and be 4–64 "
        "characters long"
    ),
    "Mã vạch '{barcode}' đã được dùng cho sản phẩm '{name}'": (
        "Barcode '{barcode}' is already used by product '{name}'"
    ),
    "Mã sản phẩm vừa được sản phẩm khác dùng. Vui lòng thử lại.": (
        "Another product has just used this product code. Please try again."
    ),
    "Mã vạch vừa được sản phẩm khác dùng. Vui lòng thử lại.": (
        "Another product has just used this barcode. Please try again."
    ),
    "Tên sản phẩm vừa được sản phẩm khác dùng. Vui lòng thử lại.": (
        "Another product has just used this name. Please try again."
    ),
    "Mã sản phẩm '{code}' đã được dùng cho sản phẩm '{name}'": (
        "Product code '{code}' is already used by product '{name}'"
    ),
    "Bạn không có quyền thao tác cửa hàng này": (
        "You do not have permission to manage this store"
    ),
    "Tên danh mục không được để trống": "Category name is required",
    "Danh mục không tồn tại": "Category not found",
    "Không có quyền chỉnh sửa danh mục của cửa hàng này": (
        "You do not have permission to edit this store's category"
    ),
    "Loại file không hợp lệ. Chỉ chấp nhận JPG, PNG, WEBP": (
        "Invalid file type. Only JPG, PNG, and WEBP are accepted"
    ),
    "Đuôi file không hợp lệ": "Invalid file extension",
    "File quá lớn (tối đa 2MB)": "File is too large (maximum 2 MB)",
    "File rỗng": "The file is empty",
    "Nội dung file không phải ảnh hợp lệ": "The file content is not a valid image",
    "Không tìm thấy sản phẩm có mã vạch '{barcode}'": (
        "No product was found with barcode '{barcode}'"
    ),
    "Sản phẩm với tên này đã tồn tại trong cửa hàng!": (
        "A product with this name already exists in the store!"
    ),
    "Giá sản phẩm phải lớn hơn 0": "Product price must be greater than 0",
    "Số lượng tồn kho không được âm": "Stock quantity cannot be negative",
    "Sản phẩm không tồn tại": "Product not found",
    "Tên sản phẩm không được để trống": "Product name is required",
    "Danh mục không thuộc cửa hàng này": "This category does not belong to the store",
    "Chưa có sản phẩm nào được đếm": "No products have been counted",
    "Một sản phẩm xuất hiện nhiều lần trong phiếu kiểm kê": (
        "A product appears more than once in the stocktake"
    ),
    "Số đếm không được âm": "Counted quantity cannot be negative",
    "Số lượng thay đổi phải khác 0": "Stock adjustment must not be 0",
    "Không đủ tồn kho để xuất {quantity} (hiện còn {stock})": (
        "Not enough stock to remove {quantity} (currently {stock})"
    ),

    # Cash shifts
    "Vui lòng nhập lý do thu/chi": "Enter a reason for this cash movement",
    "Không tìm thấy ca làm việc": "Shift not found",
    "Bạn không có quyền thao tác ca này": (
        "You do not have permission to manage this shift"
    ),
    "Tiền đầu ca không hợp lệ": "Invalid opening cash amount",
    "page phải >= 1": "page must be at least 1",
    "per_page phải từ 1 đến {maximum}": (
        "per_page must be between 1 and {maximum}"
    ),
    "Số tiền thu/chi phải lớn hơn 0": "Cash movement amount must be greater than 0",
    "Mã thao tác không hợp lệ": "Invalid operation ID",
    "Mã thao tác đã được dùng cho một khoản thu/chi khác": (
        "This operation ID was already used for another cash movement"
    ),
    "Ca làm việc đã đóng": "This shift has already been closed",
    "Tiền chi không được vượt tiền dự kiến trong ca ({amount}đ)": (
        "Cash paid out cannot exceed the expected cash in the shift ({amount} VND)"
    ),
    "Tiền thực đếm không hợp lệ": "Invalid counted cash amount",
    "Không thể đóng ca ở trạng thái hiện tại": (
        "The shift cannot be closed in its current state"
    ),
    "Ca còn {count} đơn tiền mặt chưa thanh toán; hãy thanh toán hoặc hủy trước khi đóng ca": (
        "This shift still has {count} unpaid cash order(s). Pay or cancel them "
        "before closing the shift."
    ),
    "Ca lệch tiền; vui lòng nhập ghi chú giải trình": (
        "The cash count does not match. Enter an explanation before closing the shift."
    ),
    "{field} phải theo định dạng YYYY-MM-DD": "{field} must use YYYY-MM-DD format",
    "tu_ngay không được lớn hơn den_ngay": (
        "The start date must not be later than the end date"
    ),

    # Orders, checkout and reconciliation
    "Hãy mở ca của bạn tại POS trước khi ghi nhận tiền mặt": (
        "Open your POS shift before recording a cash transaction"
    ),
    "Ca vừa được đóng; vui lòng tải lại và mở ca mới": (
        "The shift was just closed. Reload the page and open a new shift."
    ),
    "Mã retry tạo đơn đã được dùng cho một đơn khác": (
        "This order retry ID was already used for another order"
    ),
    "Đơn hàng không có sản phẩm nào": "The order has no products",
    "Khách hàng không tồn tại trong cửa hàng này": (
        "This customer does not belong to the store"
    ),
    "Không tìm thấy đơn hàng": "Order not found",
    "Không tìm thấy cửa hàng của đơn hàng": "The order's store was not found",
    "Không có quyền truy cập đơn hàng này": (
        "You do not have permission to access this order"
    ),
    "Đơn chuyển khoản phải chờ ngân hàng xác nhận tự động": (
        "Bank transfer orders must wait for automatic bank confirmation"
    ),
    "Tiền khách đưa phải ít nhất {amount}đ": (
        "Cash received must be at least {amount} VND"
    ),
    "Không thể xác nhận thanh toán cho đơn ở trạng thái {status}": (
        "Payment cannot be confirmed while the order is in status {status}"
    ),
    "Chỉ được thu bù tiền mặt cho đơn chuyển thiếu đang chờ đối soát": (
        "Cash can only be collected for an underpaid order awaiting review"
    ),
    "Đơn không còn thiếu tiền": "The order no longer has an outstanding balance",
    "Tiền mặt phải bù đúng toàn bộ phần còn thiếu là {amount}đ": (
        "The cash payment must cover the full outstanding balance of {amount} VND"
    ),
    "Số tiền bù phải lớn hơn 0": "The additional payment must be greater than 0",
    "Số tiền của đơn vừa thay đổi; vui lòng tải lại trước khi thu bù": (
        "The order balance has changed. Reload it before collecting the balance."
    ),
    "Mã thao tác hoàn tiền không hợp lệ": "Invalid refund operation ID",
    "Mã thao tác hoàn tiền đã được dùng cho một giao dịch khác": (
        "This refund operation ID was already used for another transaction"
    ),
    "Đơn hàng không có khoản tiền cần hoàn": "This order has no refund due",
    "Trạng thái đối soát của đơn không cho phép ghi nhận hoàn tiền": (
        "The order's review status does not allow a refund to be recorded"
    ),
    "Khoản cần hoàn vừa thay đổi; vui lòng tải lại trước khi xác nhận": (
        "The refund amount has changed. Reload it before confirming."
    ),
    "Không thể hủy đơn ở trạng thái {status}": (
        "An order in status {status} cannot be cancelled"
    ),
    "Không tìm thấy mã đơn hàng ORDERxxx trong thông tin thanh toán": (
        "No ORDERxxx order reference was found in the payment information"
    ),
    "Không tìm thấy đơn hàng tương ứng": "No matching order was found",
    "Đã thu đủ và hoàn tất đơn hàng": (
        "The balance has been collected and the order is complete"
    ),
    "Đã ghi nhận khoản tiền mặt bù thiếu": (
        "The additional cash payment has been recorded"
    ),
    "Lần hoàn tiền này đã được ghi nhận trước đó": (
        "This refund operation was already recorded"
    ),
    "Khoản hoàn tiền này đã được ghi nhận trước đó": (
        "This refund was already recorded"
    ),
    "Đã ghi nhận hoàn tiền thành công": "The refund was recorded successfully",

    # Vietnamese speech service (the spoken money remains Vietnamese)
    "Server chưa cấu hình giọng đọc (thiếu TTS_PROVIDER/TTS_API_KEY)": (
        "The speech service is not configured "
        "(TTS_PROVIDER/TTS_API_KEY is missing)"
    ),
    "Azure cần TTS_AZURE_REGION (ví dụ: southeastasia)": (
        "Azure requires TTS_AZURE_REGION (for example: southeastasia)"
    ),
    "Google không trả về dữ liệu âm thanh": "Google returned no audio data",
    "Thiếu nội dung cần đọc": "Text to speak is required",
    "Nội dung quá dài (tối đa {maximum} ký tự)": (
        "The text is too long (maximum {maximum} characters)"
    ),
    "TTS_PROVIDER='{provider}' không hỗ trợ. Dùng 'google' hoặc 'azure'.": (
        "TTS_PROVIDER='{provider}' is not supported. Use 'google' or 'azure'."
    ),
    "Nhà cung cấp giọng đọc lỗi {code}": (
        "The speech provider returned error {code}"
    ),
    "Không kết nối được nhà cung cấp giọng đọc": (
        "Could not connect to the speech provider"
    ),
    "Nhà cung cấp trả về dữ liệu rỗng": (
        "The speech provider returned empty data"
    ),

    # Email
    "F-Selling: Mã xác minh của bạn": "F-Selling: Your verification code",
    "F-Selling: Xác minh tài khoản mới": "F-Selling: Verify your new account",
    "F-Selling: Gửi lại mã xác minh tài khoản": "F-Selling: New account verification code",
    "F-Selling: Mã khôi phục mật khẩu": "F-Selling: Password recovery code",
    "Mã xác minh F-Selling": "F-Selling verification code",
    "Chào bạn,": "Hello,",
    "Mã xác minh (OTP) của bạn là:": "Your verification code (OTP) is:",
    "Mã này có hiệu lực trong vòng 15 phút. Vui lòng không chia sẻ mã này với bất kỳ ai.": (
        "This code is valid for 15 minutes. Do not share it with anyone."
    ),
    "Hệ thống F-Selling - Ứng dụng bán hàng thông minh.": (
        "F-Selling — Smart point-of-sale software."
    ),

    # Excel exports
    "Doanh thu Shops": "Store revenue",
    "Tên Shop": "Store name",
    "Tổng Doanh Thu": "Total revenue",
    "Lịch sử giao dịch": "Transaction history",
    "Mã đơn": "Order ID",
    "Ngày tạo": "Created at",
    "Thu ngân": "Cashier",
    "Mã ca": "Shift ID",
    "Trạng thái": "Status",
    "Thành tiền": "Total",
    "Tổng Doanh Thu (Đã thanh toán)": "Total revenue (paid orders)",
    "Chờ thanh toán": "Awaiting payment",
    "Đã thanh toán": "Paid",
    "Đã hủy": "Cancelled",
    "Cần đối soát": "Needs review",
}
