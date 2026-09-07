# Phần mềm AI Dịch & Lồng tiếng Video — Bản đặc tả thiết kế

Trạng thái: Đã được người dùng phê duyệt (2026-09-07). Sẵn sàng cho việc lập kế hoạch triển khai.

## 1. Mục đích & Phạm vi

Một ứng dụng web nhận video do người dùng tải lên (hoặc một URL YouTube/TikTok), phiên âm giọng nói, dịch nó, tạo giọng nói lồng tiếng bằng ngôn ngữ đích, đồng bộ hóa âm thanh mới với thời gian gốc của video, và tạo ra một video cuối cùng để người dùng xem trước và xuất ra — có thể kèm theo phụ đề tiếng Việt.

Trường hợp sử dụng chính: người dùng dịch và lồng tiếng lại các video YouTube/TikTok của chính họ (nguồn: EN/ZH/JA) sang tiếng Việt để đăng lại. Sản phẩm được xây dựng cho mục đích sử dụng cá nhân/nội bộ trước, nhưng kiến trúc (đầy đủ tính năng xác thực, hạn mức phút cho từng người dùng, vai trò quản trị viên) được thiết kế để sau này có thể phát triển thành một SaaS (Phần mềm dạng dịch vụ) công cộng mà không cần viết lại mã.

## 2. Tóm tắt yêu cầu

### Người dùng & Quyền truy cập
- Đăng ký/đăng nhập đầy đủ qua Supabase Auth.
- Vai trò: `user` (người dùng) và `admin` (quản trị viên).
- Quản trị viên có thể xem tất cả người dùng và đặt hạn mức số phút hàng tháng cho mỗi người dùng.

### Ngôn ngữ
- Các ngôn ngữ nguồn tích cực hỗ trợ: Tiếng Anh, Tiếng Trung, Tiếng Nhật.
- Ngôn ngữ đích tích cực hỗ trợ: Tiếng Việt.
- Quy trình xử lý được thiết kế không phụ thuộc ngôn ngữ (bất kỳ → bất kỳ); ngôn ngữ nguồn/đích là các trường thông tin của mỗi dự án, không bị hardcode.
- Ngôn ngữ giao diện (UI): Chỉ tiếng Việt. Không cần framework đa ngôn ngữ (i18n) ở giai đoạn này.

### Đầu vào Video
- Thời lượng tối đa: 60 phút. Dung lượng file tối đa: 2 GB.
- Định dạng chấp nhận: bất kỳ định dạng nào FFmpeg có thể đọc (MP4, MOV, MKV, AVI, WebM, FLV, …).
- Phương thức đầu vào: tải file trực tiếp, hoặc nhập URL từ YouTube/TikTok qua `yt-dlp` (đối với các video mà người dùng sở hữu/có bản quyền).
- Xử lý mỗi lần một video trên mỗi dự án; nhiều dự án có thể được xếp hàng đợi xử lý tuần tự (không có yêu cầu xử lý song song).
- Độ phân giải đầu ra: người dùng có thể chọn cho mỗi lần xuất. Hành vi mặc định là sao chép luồng video gốc (không encode lại, không giảm chất lượng, nhanh) khi người dùng giữ nguyên độ phân giải; việc encode lại chỉ xảy ra khi người dùng chủ động chọn một độ phân giải khác.
- Tỷ lệ khung hình đầu ra luôn khớp với nguồn (không tự động cắt thành 9:16).

### Chuyển giọng nói thành văn bản (Speech-to-Text)
- Engine chính: **ElevenLabs Scribe** (có dấu thời gian ở mức độ từng từ + phân tách người nói trong một lần gọi API).
- Engine dự phòng: **Whisper chạy local** (`faster-whisper`, mô hình mặc định kích thước `medium`), được tự động sử dụng khi Scribe bị lỗi hoặc tài khoản hết hạn mức ElevenLabs.
- Bắt buộc phải có tính năng phân tách người nói (Diarization) — một số video nguồn có nhiều người nói, và mỗi người nói sau này sẽ được ánh xạ tới một giọng lồng tiếng riêng biệt.

### Dịch thuật
- Engine được chọn theo từng dự án: **Gemini** hoặc **OpenAI**, cả hai key đã được người dùng sở hữu (`.env`).
- Chiến lược dịch thuật: toàn bộ bản phiên âm được sử dụng làm ngữ cảnh; các đoạn văn bản được dịch theo từng khối (~10-20 câu) thay vì dịch từng câu một, để bảo toàn chính xác các đại từ/tham chiếu.
- Một **bảng thuật ngữ chung (global glossary)** (từ nguồn → từ đích, không dịch) áp dụng cho tất cả các dự án.
- Giọng điệu: tiếng Việt giao tiếp, tự nhiên (như văn nói trên YouTube/TikTok), không trang trọng/dịch sát nghĩa đen.
- Dịch thuật **không** bị gò bó phải khớp với thời lượng nói của câu gốc — ý nghĩa đầy đủ được bảo toàn ngay cả khi làm cho câu dài hơn hoặc ngắn hơn bản gốc. Sự lệch thời gian sẽ được xử lý ở bước sau (xem §Đồng bộ thời gian).

### Đồng bộ thời gian
Thứ tự các cách điều chỉnh được áp dụng cho mỗi đoạn (segment), ưu tiên cách rẻ nhất/ít ảnh hưởng nhất trước:
1. **Tốc độ nói** của TTS được điều chỉnh theo từng đoạn để đạt được thời lượng gần nhất có thể với đoạn gốc.
2. Khoảng lặng tự nhiên giữa các đoạn được dùng làm khoảng đệm/thời gian co giãn.
3. Giải pháp cuối cùng, FFmpeg `atempo` sẽ kéo giãn/nén âm thanh được tạo ra để bắt buộc khớp với khung thời gian của đoạn gốc.

### Chuyển văn bản thành giọng nói (Text-to-Speech)
- Engine chính: **edge-tts** (miễn phí, giọng tiếng Việt tự nhiên: HoaiMy/NamMinh). Đây là một API không chính thức và có thể ngừng hoạt động mà không báo trước.
- Khi edge-tts bị lỗi, người dùng sẽ được **thông báo và hỏi** xem có muốn chuyển sang dự phòng bằng **Gemini TTS** không — đây không phải là chuyển đổi ngầm tự động.
- Lựa chọn giọng nói: người dùng chọn từ danh mục giọng nói, có âm thanh nghe thử. Các người nói được phát hiện sẽ tự động ánh xạ tới các giọng riêng biệt; người dùng có thể ghi đè và điều chỉnh tốc độ/cao độ của từng giọng.
- Không sao chép giọng nói (Voice cloning) (được loại bỏ rõ ràng khỏi phạm vi — chất lượng sao chép giọng tiếng Việt kém và máy tính của người dùng không có GPU).

### Trộn âm thanh (Audio Mixing)
Được chọn **theo từng dự án**, một trong các tùy chọn:
- **A. Nền im lặng** — chỉ có track giọng tiếng Việt mới, âm thanh gốc bị xóa hoàn toàn.
- **B. Giữ lại nhạc** — giọng nói gốc được loại bỏ qua việc tách nguồn bằng **Demucs**, giọng mới được trộn đè lên phần nhạc nền/hiệu ứng còn lại, có thanh trượt điều chỉnh âm lượng cho người dùng. (Lưu ý: Demucs chạy trên CPU có tốc độ khoảng 1.5× thời gian thực — chỉ riêng bước tách âm của video 60 phút sẽ mất ~90 phút).
- **C. Ducking (Giảm âm nền)** — giữ nguyên toàn bộ âm thanh gốc nhưng tự động giảm âm lượng xuống dưới track giọng mới, có thanh trượt điều chỉnh cho người dùng.

### Phụ đề
- Chỉ tiếng Việt (không có yêu cầu phụ đề ngôn ngữ nguồn hoặc song ngữ).
- Định dạng: SRT.
- 3 sản phẩm đầu ra được tạo ra cùng lúc:
  1. Một file `.srt` độc lập (có thể tải xuống).
  2. Một video với phụ đề **được nhúng mềm (soft-embedded)** (có thể bật/tắt trong các trình phát hỗ trợ, ví dụ: track phụ đề MKV/MP4).
  3. Một video thứ hai với phụ đề **được ghi cứng (burned in)** (hardcode, không thể tắt), với kích thước/màu sắc/vị trí font chữ do người dùng cấu hình (Phong cách TikTok: chữ to, viền đen, căn giữa).

### Chỉnh sửa (Editing)
- Kiểu trình chỉnh sửa: bảng danh sách câu (dấu thời gian | văn bản nguồn | văn bản dịch | phát | tạo lại) cho phiên bản đầu tiên. Trình chỉnh sửa dạng sóng/dòng thời gian (waveform/timeline) được hoãn lại rõ ràng cho giai đoạn sau.
- Người dùng có thể chỉnh sửa: văn bản phiên âm nguồn, và văn bản dịch.
- Người dùng có thể xem trước (phát) riêng lẻ từng câu đã lồng tiếng, và có thể tạo lại âm thanh lồng tiếng của chỉ một câu (không phải toàn bộ video) sau khi chỉnh sửa nó.

### Xử lý / Tác vụ nền (Background Jobs)
- Tất cả các thao tác nặng (phiên âm, dịch, lồng tiếng, xuất) đều chạy dưới dạng **tác vụ nền** (Celery + Redis), không bao giờ chạy đồng bộ bên trong một HTTP request, để tránh timeout đối với các video 60 phút.
- Giao diện hiển thị phần trăm tiến trình từng bước cộng với log thời gian thực, được phân phối qua **WebSocket**.
- Đóng tab trình duyệt sẽ **không** dừng quá trình xử lý — tác vụ tiếp tục ở phía server và người dùng sẽ thấy kết quả khi họ quay lại.

### Lưu trữ & Vòng đời dữ liệu
- File (video nguồn, âm thanh trung gian, các file xuất cuối cùng) được lưu trữ trên **Cloudflare R2**.
- Các file trung gian tạm thời (âm thanh được trích xuất, các luồng âm thanh đã tách, các clip TTS từng đoạn) sẽ bị xóa ngay khi chúng không còn cần thiết cho bước tiếp theo.
- Toàn bộ dự án (video + file xuất) sẽ bị xóa sau 7 ngày kể từ khi tạo; người dùng được cảnh báo trong app 1 ngày trước khi xóa.

### Cơ sở dữ liệu (Database)
- **PostgreSQL được host trên Supabase**, dùng cho cả môi trường dev (phát triển local) và production (không có instance Postgres local riêng biệt) — đây là sự đánh đổi có chủ ý được người dùng chấp nhận: việc phát triển local yêu cầu có kết nối mạng tới Supabase.
- **Supabase Auth** cung cấp tính năng xác thực; backend sẽ xác minh chuỗi JWT do Supabase cấp trên mỗi request.

### Các màn hình (Screens)
Trang chủ (Landing page) · Đăng nhập/Đăng ký · Bảng điều khiển (Danh sách dự án + mức sử dụng) · Dự án mới (Tải lên/URL + ngôn ngữ + chọn chế độ âm thanh) · Trình chỉnh sửa (phiên âm + dịch + gán giọng nói, các tab trên cùng một màn hình) · Xem trước/Xuất · Cài đặt (Bảng thuật ngữ chung, tùy chọn giọng nói mặc định) · Admin (Danh sách người dùng, hạn mức mỗi người dùng, tổng quan mức sử dụng/chi phí) · Lịch sử dự án.

### Hạn mức & Theo dõi chi phí
- Mọi lệnh gọi API bên ngoài (STT/dịch/TTS) đều được ghi log lại với nhà cung cấp, thao tác, chi phí, và số lượng đơn vị, gắn liền với người dùng và dự án — nhằm mục đích hiển thị, không tự động thực thi vượt quá giới hạn hạn mức.
- Quản trị viên thiết lập số phút tối đa mỗi tháng cho từng người dùng một cách thủ công (không có công thức cố định).

### API Keys / Secrets
- Tất cả các API keys của bên thứ ba (ElevenLabs, Gemini, OpenAI, Supabase, Cloudflare R2) đều được cung cấp qua file `.env` cho thời điểm hiện tại. Người dùng tự đăng ký các dịch vụ này; dự án này chỉ cung cấp tài liệu hướng dẫn cài đặt. Không có màn hình UI cài đặt "nhập API key của bạn" trong app được xây dựng ở giai đoạn này.

## 3. Kiến trúc (Architecture)

```
┌─────────────┐      REST + WebSocket      ┌──────────────────┐
│  Next.js    │ ─────────────────────────▶│  FastAPI backend │
│  (Tailwind+ │                            │  (xác minh      │
│  shadcn/ui) │◀─── WS progress/log ───────│   Supabase JWT)  │
└─────────────┘                            └─────────┬─────────┘
       │                                             │ enqueue
       │ Supabase Auth SDK                           ▼
       │                                   ┌──────────────────┐
       ▼                                   │  Redis (queue)   │
┌─────────────┐                            └─────────┬─────────┘
│  Supabase   │                                      ▼
│  (Postgres+ │                            ┌──────────────────┐
│   Auth)     │◀──── SQLModel ─────────────│  Celery workers  │
└─────────────┘                            │  - STT (ElevenLabs/│
                                           │    Whisper local)│
┌─────────────┐                            │  - Dịch          │
│  Cloudflare │◀──── upload/download ──────│    (Gemini/OpenAI)│
│  R2 (video, │                            │  - TTS (edge-tts/ │
│   audio)    │                            │    Gemini TTS)   │
└─────────────┘                            │  - FFmpeg/Demucs │
                                           │    (sync + mux)  │
                                           └──────────────────┘
```

Docker Compose (cùng 1 file cho dev và prod, khác biến môi trường) sẽ chạy: API backend, Celery worker, Redis, frontend. Postgres cố ý **không** nằm trong compose file — Supabase (remote) được sử dụng cho cả dev và prod theo các yêu cầu phía trên.

## 4. Tech Stack (Công nghệ sử dụng)

| Thành phần | Lựa chọn | Lý do |
|---|---|---|
| Frontend | Next.js (App Router) + TypeScript + TailwindCSS + shadcn/ui | SSR giúp SEO cho trang chủ; shadcn/ui cung cấp bộ component hiện đại, tính tùy biến cao phù hợp với trình chỉnh sửa nhiều dữ liệu. Không có chế độ Dark mode. |
| Backend | FastAPI (Python 3.12, trong Docker) | Demucs, edge-tts, và luồng xử lý FFmpeg/âm thanh đều là Python native; tránh việc phải kết nối sang runtime thứ hai. Python 3.12 (không phải 3.14 của máy host) được dùng trong Docker để tương thích với PyTorch/Demucs/faster-whisper. |
| ORM | SQLModel + Alembic | Prisma cho Python (`prisma-client-py`) đã bị lưu trữ/không còn bảo trì (xác nhận qua GitHub — archived 2025-04-15, giới hạn ở Python 3.10). SQLModel hỗ trợ FastAPI-native, type-safe, dựa trên Pydantic; Alembic xử lý migrations. |
| Hàng đợi (Queue) | Celery + Redis | Bắt buộc vì việc xử lý video 60 phút sẽ mất hàng giờ; các tác vụ phải sống sót kể cả khi người dùng đóng tab trình duyệt. |
| Thời gian thực (Realtime) | WebSocket | Kênh 2 chiều được dùng để stream % tiến độ và các dòng log cho từng tác vụ. |
| Database / Auth | Supabase (Postgres + Auth) | Dịch vụ được host duy nhất cho cả hai, dùng nhất quán giữa dev và prod. |
| Lưu trữ (Storage) | Cloudflare R2 | Không tốn phí băng thông ra (egress fees), tối ưu chi phí cho các object kích thước lớn như video. |
| Công cụ Video/Audio | FFmpeg, Demucs, yt-dlp | FFmpeg để mux/encode/atempo; Demucs để tách giọng nói/âm nhạc; yt-dlp để tải từ YouTube/TikTok. |
| Triển khai (Deployment) | Railway (frontend + backend + worker + Redis), Supabase, Cloudflare R2 | Railway chạy được các worker process sống lâu (khác với các nền tảng serverless không thể host các tác vụ kéo dài nhiều giờ). |
| Cấu trúc Repo | Monorepo: `frontend/`, `backend/` | Chỉ cần clone một lần, có nguồn chân lý duy nhất (single source of truth) cho cả 2 nửa của ứng dụng. |

## 5. Schema Cơ sở dữ liệu (Database Schema)

```
profiles (phản chiếu supabase auth.users)
  id (= auth.users.id), email, role[user|admin], created_at

quotas
  id, user_id → profiles, minutes_limit_per_month, set_by_admin_id, updated_at

projects
  id, user_id → profiles, title, source_language, target_language,
  status[draft|transcribing|translating|dubbing|ready|failed],
  audio_mode[silent|music_separated|ducking],
  translate_engine[gemini|openai],
  created_at, updated_at, warn_at, expires_at

videos
  id, project_id → projects, source_type[upload|youtube|tiktok],
  source_url, storage_path, duration_sec, resolution, codec,
  file_size_bytes, uploaded_at

transcript_segments
  id, project_id → projects, seq_index, start_time, end_time,
  speaker_label, source_text, source_text_edited, confidence

translation_segments
  id, segment_id → transcript_segments (1-1),
  translated_text, translated_text_edited

voices
  id, project_id → projects, speaker_label, engine[edge-tts|gemini-tts],
  voice_id, speed, pitch

dubbed_segments
  id, segment_id → transcript_segments (1-1),
  audio_storage_path, duration_sec, status, generated_at

jobs
  id, project_id → projects, job_type[transcribe|translate|dub|export],
  status[queued|running|done|failed], progress_pct, current_step,
  error_message, started_at, finished_at

exports
  id, project_id → projects, export_type[video|video_hardsub|srt],
  storage_path, resolution, created_at, expires_at

glossary_terms
  id, user_id → profiles, source_term, target_term

usage_logs
  id, user_id → profiles, project_id → projects,
  api_provider, operation, cost_usd, units, created_at
```

Các quan hệ (relationships) chính: một dự án (project) có nhiều đoạn phiên âm (transcript segments); mỗi đoạn phiên âm có chính xác một đoạn dịch (translation segment) và (một khi được lồng tiếng) chính xác một đoạn âm thanh lồng tiếng (dubbed-audio segment); một dự án có nhiều giọng nói (một giọng cho mỗi người nói được phát hiện), nhiều tác vụ/jobs (mỗi bước trong pipeline chạy là một job), và nhiều bản xuất/exports (mỗi loại export được yêu cầu là một bản xuất).

## 6. Thiết kế API

Auth được xử lý ở phía client thông qua Supabase SDK; backend chỉ xác minh JWT do Supabase cấp thông qua middleware.

```
POST   /api/projects
GET    /api/projects
GET    /api/projects/{id}
PATCH  /api/projects/{id}
DELETE /api/projects/{id}

POST   /api/projects/{id}/upload            (multipart file)
POST   /api/projects/{id}/import-url        {url}

POST   /api/projects/{id}/transcribe        → đẩy vào queue Celery job
GET    /api/projects/{id}/transcript
PATCH  /api/projects/{id}/transcript/{segment_id}

POST   /api/projects/{id}/translate         {engine}  → đẩy vào queue job
GET    /api/projects/{id}/translation
PATCH  /api/projects/{id}/translation/{segment_id}

GET    /api/voices/catalog
GET    /api/voices/preview?engine=&voice_id=
PUT    /api/projects/{id}/voices            (gán giọng nói cho từng người nói)

POST   /api/projects/{id}/dub               → đẩy vào queue TTS+sync+mux job
POST   /api/projects/{id}/segments/{id}/regenerate

GET    /api/projects/{id}/preview
POST   /api/projects/{id}/export            {type: video|video_hardsub|srt}
GET    /api/projects/{id}/exports
GET    /api/projects/{id}/exports/{id}/download

GET    /api/projects/{id}/status
WS     /ws/projects/{id}/progress

GET/POST /api/glossary
GET    /api/admin/users
PATCH  /api/admin/users/{id}/quota
GET    /api/admin/usage
```

Mỗi endpoint có chức năng kích hoạt phiên âm, dịch, lồng tiếng, hoặc xuất video sẽ đưa một tác vụ nền vào hàng đợi và trả về kết quả ngay lập tức; nó không chặn (block) HTTP request trong khi tác vụ đang chạy.

## 7. Cấu trúc thư mục

```
tool/
├── frontend/                          # Next.js
│   ├── app/
│   │   ├── (auth)/login/ register/
│   │   ├── dashboard/
│   │   ├── projects/[id]/
│   │   │   ├── transcript/ translate/ voices/ preview/ export/
│   │   ├── settings/
│   │   ├── admin/
│   │   └── history/
│   ├── components/
│   ├── lib/                           # supabase client, api client, ws client
│   └── ...
│
├── backend/                           # FastAPI
│   ├── app/
│   │   ├── api/                       # routers cho từng resource
│   │   ├── models/                    # SQLModel
│   │   ├── services/
│   │   │   ├── stt/                   # elevenlabs.py, whisper_local.py
│   │   │   ├── translation/           # gemini.py, openai.py
│   │   │   ├── tts/                   # edge_tts.py, gemini_tts.py
│   │   │   ├── audio/                 # demucs.py, ducking.py, sync.py, ffmpeg_utils.py
│   │   │   ├── storage/               # r2.py
│   │   │   └── downloader/            # yt_dlp.py
│   │   ├── workers/                   # celery tasks
│   │   ├── core/                      # config, jwt auth, celery app, ws manager
│   │   ├── db/                        # session, models base
│   │   └── main.py
│   ├── alembic/
│   ├── Dockerfile
│   └── pyproject.toml
│
├── docker-compose.yml                 # backend + worker + redis + frontend
├── .env.example
├── .gitignore
└── README.md
```

## 8. Các giả định triển khai (Không chờ người dùng xác nhận thêm)

- Bản dự phòng Whisper local mặc định dùng mô hình kích thước `medium`, có thể ghi đè qua `.env`.
- Dev yêu cầu có kết nối internet để chạm tới Supabase (hệ quả trực tiếp của việc dùng Supabase trong dev, thay vì Postgres local).
- Backend chạy Python 3.12 bên trong Docker bất kể phiên bản Python của máy host là gì.
- FFmpeg được tích hợp sẵn bên trong Docker image của backend; máy host không cần phải cài đặt nó riêng lẻ.

## 9. Nằm ngoài phạm vi rõ ràng (Cho giai đoạn này)

- Sao chép giọng nói (Voice cloning).
- Trình chỉnh sửa dạng sóng/dòng thời gian (Timeline/waveform editor) (hoãn lại cho giai đoạn sau; trình chỉnh sửa danh sách câu sẽ được phát hành trước).
- Phụ đề ngôn ngữ nguồn hoặc song ngữ (hiện tại chỉ có tiếng Việt).
- Giao diện người dùng quản lý API key trong ứng dụng (các key hiện chỉ nằm trong `.env`).
- Tự động thực thi hạn mức vượt quá giới hạn thiết lập thủ công của quản trị viên.
- Bất kỳ chế độ xử lý "offline/riêng tư" nào — mọi dự án đều sử dụng các engine đám mây (cloud engines) được mô tả ở trên.

## 10. Các giai đoạn triển khai (Dành cho kế hoạch tiếp theo)

1. Thiết lập dự án — tạo khung repo (scaffolding), Docker Compose, kiểm tra tình trạng (health check) frontend/backend, kết nối Supabase, luồng dev local không cần CI.
2. Tải lên (Upload) — tải file lên + nhập URL YouTube/TikTok, trích xuất metadata của video, luồng tạo dự án.
3. Chuyển giọng nói thành văn bản (Speech-to-text) — tích hợp ElevenLabs Scribe, dự phòng Whisper local, kết nối Celery job, theo dõi tiến độ qua WebSocket.
4. Trình chỉnh sửa phiên âm (Transcript editor) — giao diện danh sách câu, chỉnh sửa/lưu văn bản của từng đoạn.
5. Dịch thuật (Translation) — tích hợp Gemini/OpenAI, dịch theo ngữ cảnh chia khối (chunk), áp dụng bảng thuật ngữ, giao diện chỉnh sửa bản dịch.
6. Chuyển văn bản thành giọng nói (Text-to-speech) — tích hợp edge-tts, prompt dự phòng Gemini TTS, danh mục giọng nói + nghe thử, giao diện ánh xạ người nói→giọng nói.
7. Luồng FFmpeg — đồng bộ thời gian (điều chỉnh tốc độ → thêm khoảng im lặng padding → atempo), tách âm Demucs / ducking, trộn (mux) thành video cuối cùng, ghi cứng phụ đề và nhúng mềm phụ đề.
8. Xem trước & Xuất (Preview & export) — trình xem trước (player), tạo lại (regenerate) theo từng đoạn, luồng xuất (video / video+hardsub / srt), tải xuống, vòng đời R2 (dọn dẹp file tạm, hết hạn sau 7 ngày kèm cảnh báo trước 1 ngày).
9. Auth, admin, hạn mức (quotas) — kết nối Supabase Auth, quyền truy cập theo vai trò (role), màn hình admin (danh sách người dùng, chỉnh sửa hạn mức, tổng quan mức sử dụng/chi phí), màn hình cài đặt (bảng thuật ngữ chung, tùy chọn giọng nói mặc định).

Mỗi giai đoạn kết thúc sau khi đã chạy tests, kiểm tra lỗi, và báo cáo lại trước khi chuyển sang giai đoạn tiếp theo — không có giai đoạn nào được tiếp tục vượt qua điểm quyết định cần người dùng xác nhận mà không dừng lại để hỏi trước.
