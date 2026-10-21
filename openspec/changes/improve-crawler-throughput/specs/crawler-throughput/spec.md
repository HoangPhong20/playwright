# Spec Delta

## Purpose

Tăng năng suất crawler bằng cách giảm công việc lặp trong listing và detail, đồng thời giữ phạm vi khách sạn thực sự quan sát được, tính đầy đủ của từng trang và hợp đồng bàn giao manifest. Cải thiện phải được xác nhận bằng benchmark local tái lập trên cùng quy tắc dữ liệu.

## ADDED Requirements

### Requirement: Membership xuất phát từ hotel cards

Crawler SHALL chỉ dùng embedded URL để bổ sung khách sạn có canonical URL hoặc property identity đã quan sát từ hotel cards trong cùng trang. Membership MUST tích lũy qua các snapshot của trang và không tự mở rộng từ embedded; tên hoặc city suffix không đủ chứng minh membership. Hai property identity xung đột MUST không được ghép. Mọi đường fallback SHALL tuân theo cùng ranh giới listing.

#### Scenario: Embedded không có card tương ứng
- **WHEN** HTML chứa URL của khách sạn không xuất hiện trong hotel cards
- **THEN** URL đó không tạo candidate cho enrichment/public, được đếm riêng và chỉ giữ mẫu diagnostics giới hạn

#### Scenario: Partial card biến mất trước full snapshot
- **WHEN** một card thiếu URL nhưng có property identity đã được quan sát ở snapshot trước, rồi embedded cung cấp URL cùng identity ở full snapshot sau
- **THEN** crawler giữ card đó và bổ sung URL dù card đã rời DOM

#### Scenario: Không đủ bằng chứng hoặc identity xung đột
- **WHEN** embedded chỉ trùng tên/city suffix, hoặc có property identity khác card đang xét
- **THEN** crawler không dùng embedded để bổ sung record đó

#### Scenario: Khách sạn lân cận nằm trong kết quả thật
- **WHEN** một hotel card hợp lệ thuộc khu vực lân cận thực sự xuất hiện trong listing
- **THEN** crawler giữ card đó, không loại chỉ vì city suffix khác destination tìm kiếm

#### Scenario: Fallback gặp recommendation ngoài listing
- **WHEN** đường fallback thấy hotel link ngoài hotel cards và không có membership đã quan sát
- **THEN** link đó không tạo record mới để enrichment/public

### Requirement: Completeness của trang được chứng minh độc lập với pagination

Crawler SHALL ghi lý do dừng mỗi trang bằng `stable`, `scroll_exhausted`, `time_cap` hoặc `max_rounds`. Hai lý do đầu SHALL đòi hỏi nội dung ổn định qua số vòng cấu hình; hết vùng cuộn còn đòi hỏi không di chuyển được qua số vòng đó. Trường hợp chỉ hết budget MUST làm job `incomplete`, kể cả khi đạt giới hạn trang hoặc thấy EOF pagination. Giữ điều kiện số record tối thiểu hiện có để áp dụng time cap; không chuyển thành hard timeout trong thay đổi này.

#### Scenario: Budget kết thúc khi trang còn tăng trưởng
- **WHEN** time cap đủ điều kiện hoặc max rounds đã đạt mà chưa có bằng chứng thu xong
- **THEN** crawler giữ partial output, ghi stop reason tương ứng và job không được complete

#### Scenario: Đủ bằng chứng và hết budget cùng lúc
- **WHEN** nội dung đã ổn định, đã đáp ứng điều kiện dừng hợp lệ, đồng thời budget vừa hết
- **THEN** lý do dừng phản ánh bằng chứng thu xong thay vì chỉ báo hết budget

#### Scenario: Full snapshot cuối phát hiện dữ liệu mới
- **WHEN** snapshot dùng để xác nhận dừng bổ sung identity hoặc field đang thiếu
- **THEN** bằng chứng ổn định cũ bị hủy; crawler xác nhận lại trong budget còn lại hoặc ghi incomplete nếu hết budget

#### Scenario: EOF không che trang chưa hoàn tất
- **WHEN** trang đầu hoặc trang sau chưa hoàn tất nhưng pagination báo EOF hoặc đã đạt max pages
- **THEN** job vẫn incomplete và batch không phát completion pointer cho attempt đó

#### Scenario: Time cap chưa đủ số record tối thiểu
- **WHEN** elapsed time vượt cap nhưng số record thấp hơn ngưỡng time-cap hiện có
- **THEN** crawler chưa dừng vì time cap; stable, scroll exhaustion hoặc max rounds vẫn có thể kết thúc trang

### Requirement: Pagination cần nội dung mới

Crawler SHALL chỉ chấp nhận chuyển trang khi có ít nhất một canonical identity chưa thuộc các trang đã chấp nhận và ít nhất hai tín hiệu xác minh hiện có. Property identity SHALL được giữ khi canonical hóa; đổi query tracking, thứ tự hoặc URL trang không tự chứng minh nội dung mới.

#### Scenario: Reorder hoặc subset của trang cũ
- **WHEN** trang đích chỉ đổi thứ tự hoặc là tập con của các identity đã có
- **THEN** crawler từ chối chuyển trang dù URL/active page/scroll có thay đổi

#### Scenario: Trang có identity mới và đủ tín hiệu
- **WHEN** có identity mới cùng ít nhất hai tín hiệu hợp lệ
- **THEN** crawler chấp nhận trang mới và cập nhật tập identity đã thấy

#### Scenario: Quay về một trang cũ không liền kề
- **WHEN** navigation đưa về identity của trang đã chấp nhận trước đó nhưng khác trang liền trước
- **THEN** crawler không chấp nhận đó là trang mới

#### Scenario: Hai property dùng chung đường dẫn
- **WHEN** hai URL dùng chung path nhưng có `propertyId` khác nhau
- **THEN** hai identity vẫn riêng biệt và property mới có thể cung cấp bằng chứng nội dung mới

### Requirement: Detail chỉ đọc và retry field cần thiết

Extraction SHALL hỗ trợ lấy toàn bộ fields theo hành vi mặc định, lấy tập fields được yêu cầu hoặc không đọc DOM khi tập yêu cầu rỗng. Fallback SHALL dựa trên parse thành công của từng field. Body SHALL chỉ được đọc khi field yêu cầu còn thiếu sau selector và tối đa một lần trong mỗi extraction. Retry SHALL chỉ đọc lại field còn thiếu, giữ số retry/timeout cấu hình và chỉ merge vào field đang thiếu.

#### Scenario: Selector có text nhưng parse thất bại
- **WHEN** selector chứa `8.6` không đủ cho parser của field và body chứa rating/review hợp lệ
- **THEN** field chưa parse được vẫn được fallback sang body, độc lập với field đã lấy thành công

#### Scenario: Chỉ yêu cầu review count
- **WHEN** record chỉ thiếu review count trong target fields
- **THEN** extraction không đọc selector giá, tên hoặc star rating không cần thiết

#### Scenario: Tất cả selector yêu cầu đã parse được
- **WHEN** mọi field yêu cầu đã có giá trị hợp lệ từ selector
- **THEN** extraction không đọc body

#### Scenario: Nhiều field cần fallback
- **WHEN** nhiều field yêu cầu chưa parse được từ selector
- **THEN** một lần đọc body phục vụ tất cả field còn thiếu trong extraction đó

#### Scenario: Retry sau khi đã lấy được giá
- **WHEN** lần đầu lấy được giá nhưng còn thiếu rating hoặc review
- **THEN** retry chỉ đọc các field còn thiếu và không ghi đè giá đã có

#### Scenario: Selector đầu không tồn tại
- **WHEN** selector sau trong nhóm target đã xuất hiện nhưng selector đầu không có
- **THEN** chờ bất kỳ selector target kết thúc mà không phải tiêu timeout lần lượt cho các selector vắng mặt

#### Scenario: Một detail record lỗi
- **WHEN** navigation hoặc extraction của một record thất bại
- **THEN** lỗi được ghi cho record đó, các record khác tiếp tục và tài nguyên/slot đã nhận được giải phóng đúng đường lỗi

### Requirement: Giảm payload không thay quy tắc listing

Crawler SHALL chỉ tạo HTML preview khi cần diagnostics hoặc bật debug, đồng thời giữ đủ bằng chứng lọc carousel/filter. Crawler SHALL giữ merge trong lúc cuộn, snapshot thường trước/sau scroll, full snapshot interval và full snapshot xác nhận cuối trang; không thay heuristic bằng số card đơn thuần.

#### Scenario: Carousel hoặc filter cần thuộc tính HTML để nhận diện
- **WHEN** dấu hiệu loại DOM nằm ở attribute trong HTML thay vì text/class của card
- **THEN** việc bỏ preview không biến DOM đó thành partial hotel candidate

#### Scenario: URL hoặc giá xuất hiện muộn
- **WHEN** field chỉ xuất hiện sau một lần cuộn hoặc full snapshot cuối
- **THEN** field vẫn được bổ sung vào cùng record và được tính khi đánh giá ổn định

#### Scenario: Card partial cần điều tra
- **WHEN** card thiếu URL hoặc bị phân loại invalid
- **THEN** diagnostics vẫn có bằng chứng đủ dùng trong phạm vi batch/destination/check-in, với số mẫu và độ dài bị giới hạn

### Requirement: Metrics không phụ thuộc record được publish

Log và manifest SHALL có summary listing/detail theo page/job/batch kể cả job không có public record. Metrics SHALL phân biệt wall time và tổng thời gian nhiều worker; đo riêng DOM call, embedded scan, parse/dedupe, merge, chờ và overhead. Tổng vòng/max vòng SHALL lấy từ page results. Attempts, failures, retries SHALL bao gồm ứng viên bị discard; slot wait SHALL tính mỗi lần acquire thực sự, không nhân theo số record.

#### Scenario: Ứng viên đã thử detail bị discard
- **WHEN** một ứng viên đã được thử detail nhưng cuối cùng thiếu required field
- **THEN** attempts/failures/retries và thời gian của nó vẫn xuất hiện trong summary toàn bộ ứng viên

#### Scenario: Snapshot nằm trong vòng chờ
- **WHEN** vòng chờ đồng thời thực hiện snapshot và parse/merge
- **THEN** báo cáo tổng thời gian không cộng trùng snapshot vào phần chờ chủ động

#### Scenario: Nhiều record dùng chung một detail slot
- **WHEN** worker acquire slot một lần rồi xử lý nhiều record
- **THEN** thời gian acquire chỉ tính một lần, có số lần acquire và số worker đi kèm

#### Scenario: Retry pagination hoặc job rỗng
- **WHEN** một probe/collection bị từ chối hoặc job không trả record
- **THEN** chi phí đã thực hiện vẫn được giữ ở metrics job, không biến mất khi aggregate public records

### Requirement: Benchmark dùng cùng contract và mẫu chạy cố định

Benchmark SHALL dùng hai baseline sau khi có metrics và bảo vệ correctness, trước tối ưu detail/payload; sau đó ABBA 3/2/2/3 và hai full candidate. Full profile SHALL là Vũng Tàu, Đà Nẵng, Nha Trang, TP.HCM × tối đa 5 trang, workers=2, global detail cap=3; cùng ngày check-in tương lai, occupancy, thứ tự destination và cấu hình khác. Mỗi run SHALL có identity/output mới và provenance tái lập.

#### Scenario: So sánh baseline với candidate
- **WHEN** tính throughput
- **THEN** dùng `publishable_records * 60 / batch_wall_seconds` trên toàn batch, không lấy tổng thời gian job làm mẫu số

#### Scenario: Run thiếu phạm vi hoặc bị lỗi
- **WHEN** có job failed/incomplete, thiếu EOF hợp lệ khi dừng sớm, không có public record hoặc discard vượt 10%
- **THEN** run không đủ điều kiện benchmark; báo cáo vẫn giữ run lỗi, không thay bằng lượt chạy thêm tự động

#### Scenario: Chọn concurrency từ ABBA
- **WHEN** cả hai lượt của một cấu hình hợp lệ
- **THEN** so median throughput để chọn; hòa giữ per-job=3, không cấu hình hợp lệ thì dừng quyết định

#### Scenario: Xác nhận lợi ích full profile
- **WHEN** median hai candidate cao hơn median hai baseline và từng candidate cũng cao hơn median baseline, cùng đạt các điều kiện chất lượng và tài nguyên trong design
- **THEN** kết luận có cải thiện quan sát được, không yêu cầu phần trăm tăng tối thiểu và không suy rộng thành bảo đảm thống kê

#### Scenario: Bốn full attempts đã dùng hết
- **WHEN** chưa đủ bằng chứng kết luận sau ngân sách hai baseline và hai candidate
- **THEN** báo chưa xác nhận, giữ mặc định và không tự mở rộng ngân sách

### Requirement: Giữ hợp đồng public và downstream

Crawler MUST giữ required fields, định dạng giá VND dương, optional coverage warning hiện có, immutable attempts và semantics completion pointer. Summary mới SHALL bổ sung vào manifest mà không đổi điều kiện chấp nhận complete. Discard ≤10% SHALL chỉ là tiêu chí benchmark, không thành pipeline gate mới. Kiểm chứng Airflow/Databricks SHALL giới hạn ở local contract tests.

#### Scenario: Manifest complete có metrics mới
- **WHEN** manifest đủ điều kiện cũ và có thêm metrics/page stop reasons
- **THEN** validator và consumer local tiếp tục chấp nhận, public JSONL không có metadata mới

#### Scenario: Optional coverage thấp
- **WHEN** rating/review/star coverage không vượt ngưỡng cấu hình hiện có
- **THEN** pipeline giữ warning policy; benchmark báo chất lượng và áp dụng quy tắc so sánh đã chốt riêng

#### Scenario: Incomplete attempt và complete attempt cũ
- **WHEN** một attempt mới incomplete sau một attempt cũ complete trong cùng batch
- **THEN** attempt mới không được phát pointer thay cho attempt cũ; test dùng identity mới để chứng minh không tạo pointer mới
