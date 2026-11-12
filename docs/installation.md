# Installation & Configuration

[← Documentation home](README.md)

- [Requirements](#requirements)
- [Install](#install)
- [AI model files](#ai-model-files)
- [Downloading SAM3](#downloading-sam3)
- [GPU acceleration](#gpu-acceleration)
- [Configuration (`.env`)](#configuration-env)
- [Troubleshooting](#troubleshooting)

---

## Requirements

| | Version | Needed for |
|---|---|---|
| **Python** | 3.10 or newer | everything |
| **ffmpeg** on `PATH` | any recent | turning videos into frames (recommended; an OpenCV fallback handles common formats, but not CCTV `.dav` or H.265 reliably) |
| **NVIDIA GPU** | optional | fast AI labelling (everything also runs on CPU) |

`requirements.txt` is grouped by feature: **1 · Core app** is enough for manual annotation; **2 · AI base** adds Smart Detect; **3 · SAM3** adds AI Annotate text and box prompts.

## Install

```bash
# 1. Clone
git clone https://github.com/ChandraMahesh24/Annomaster1.git
cd Annomaster1

# 2. Virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux / macOS

# 3. Dependencies   (for an NVIDIA GPU, see "GPU acceleration" first)
pip install -r requirements.txt

# 4. Configuration
cp .env.example .env           # then set SECRET_KEY and JWT_SECRET

# 5. Run
python run.py
```

Open **<http://localhost:5000>**, register an account, create a workspace and a project, and upload your first images.

Schema updates for an existing database are applied with `python migrate_db.py` (safe to run repeatedly).

## AI model files

| Model | Used for | How to get it |
|---|---|---|
| **Your YOLO `.pt`** | Smart Detect | Upload it in the app, or put it in `models/` |
| **SAM3** (`sam3.pt`, ≈3.45 GB) | Text and box prompts | Gated by Meta. See [Downloading SAM3](#downloading-sam3) |
| **DINOv2-small** (85 MB) | Box prompts: decides the class | Downloaded automatically on first use |
| **OpenAI CLIP** | SAM3's text encoder | Installed by `requirements.txt` |

Manual annotation needs **none** of these. Without `sam3.pt`, the AI Annotate panel explains what is missing and the rest of the app works normally.

## Downloading SAM3

SAM3 is published by Meta on Hugging Face as a **gated** model: anyone can use it, but you must accept its licence first, so the app cannot download it on your behalf.

**1. Request access** (once per Hugging Face account)

1. Sign in or create a free account at [huggingface.co](https://huggingface.co/join).
2. Open **[huggingface.co/facebook/sam3](https://huggingface.co/facebook/sam3)**, read the licence and click **Agree and access repository**.
3. Wait for approval. Meta reviews requests by hand, which can take from minutes to a few days; Hugging Face emails you when access is granted.

**2. Download `sam3.pt`**

*Browser:* on the model page open **Files and versions**, click **`sam3.pt`**, then the download icon.

*Command line* (resumes if the connection drops):

```bash
# create a "Read" access token at https://huggingface.co/settings/tokens
hf auth login                                   # paste the token when asked
hf download facebook/sam3 sam3.pt --local-dir models
```

> `hf` comes with `huggingface_hub`, which `requirements.txt` installs. Older versions call it `huggingface-cli`.

**3. Put it in place**

Place `sam3.pt` in `models/` (the command above already does this) or next to `run.py`, then refresh the annotate page. The engine list changes from **"SAM3 (needs weights)"** to **"SAM3"**; no restart is needed.

> `.gitignore` excludes `*.pt` in the repository root and in `models/` (GitHub rejects files over 100 MB), except small project models such as `models/blackshirt_*.pt`.

## GPU acceleration

`requirements.txt` installs the CPU build of PyTorch. For an NVIDIA GPU, install the CUDA build **before** `requirements.txt`:

```bash
pip install torch==2.14.1+cu130 torchvision==0.29.1+cu130 --index-url https://download.pytorch.org/whl/cu130
```

> **Windows:** *Smart App Control* (Windows Security → App & browser control) must be **off**, or Windows blocks the CUDA build of PyTorch from loading (`WinError 4551`). Turning it off cannot be undone without resetting Windows.

The app chooses the device automatically: GPU with half precision when available, otherwise CPU, and it falls back to the CPU on its own if the GPU runs out of memory. The AI panel shows **"Runs on GPU (name)"** or **"Runs on CPU"**.

Measured on a 1920×1080 frame:

| Task | GPU (RTX 3050, 6 GB) | CPU |
|---|:---:|:---:|
| SAM3 text prompt | **≈0.65 s** per phrase | ≈15–20 s |
| Box-prompt prediction | **≈0.9 s** per image | ≈22–40 s |
| Smart Detect (YOLO) | **≈0.02 s** | ≈0.1 s |

The first AI request after the server starts also loads the model (≈15–20 s on GPU).

## Configuration (`.env`)

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | — | Flask secret (**required**) |
| `JWT_SECRET` | — | Signs login tokens (**required**) |
| `DATABASE_URL` | `sqlite:///annomaster.db` | Database location |
| `JWT_EXPIRY_HOURS` | `24` | How long a login lasts |
| `APP_BASE_URL` | *(empty)* | Base of password-reset links, e.g. `https://annotate.example.com`. Empty = the address the browser used. Set it in production |
| `RESET_TOKEN_MINUTES` | `30` | Password-reset link lifetime |
| `MAIL_SERVER` … `MAIL_FROM` | *(empty)* | SMTP settings. Empty = reset links are written to the server log instead of emailed |
| `AI_DEVICE` | `auto` | `auto` · `cpu` · `cuda` · `cuda:1` |
| `AI_HALF` | `auto` | `auto` = half precision on GPU · `0` = always full precision |
| `AI_APPEARANCE` | `dinov2` | Class judge for box prompts: `dinov2` · `sam3` |

## Troubleshooting

**Login fails with `module 'jwt' has no attribute 'encode'`**
The unrelated `jwt` package is installed instead of **PyJWT**:

```bash
pip uninstall jwt
pip install PyJWT
```

**`import torch` fails with `WinError 4551 … Application Control policy has blocked`**
Windows Smart App Control is blocking the CUDA build of PyTorch. Turn it off (see [GPU acceleration](#gpu-acceleration)) or reinstall the CPU build:
`pip install --no-deps --force-reinstall torch==2.14.1+cpu torchvision==0.29.2+cpu --index-url https://download.pytorch.org/whl/cpu`

**AI Annotate shows "SAM3 (needs weights)"**
`sam3.pt` is not in `models/` or next to `run.py`. See [Downloading SAM3](#downloading-sam3).

**A video won't convert into frames, or CCTV `.dav` / H.265 files fail**
`ffmpeg` is probably not on your `PATH`, so the app is using its OpenCV fallback, which cannot decode every format. Run `ffmpeg -version` in a terminal to check, then install ffmpeg.
