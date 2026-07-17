# CardioTrack CT-200 - QA Traceability API

A FastAPI-based application that provides document versioning, search, and AI-assisted QA traceability for the CardioTrack CT-200 manual.

The application allows users to upload multiple versions of a document, compare changes across versions, create version-pinned selections, and generate QA test cases using an LLM (or the built-in mock provider).

---

## Tech Stack

- FastAPI
- Pydantic
- SQLAlchemy
- SQLite
- JSON Document Store
- Pytest

---

## Project Structure

```
project/
│── app/
│── data/
│── scripts/
│── tests/
│── requirements.txt
│── README.md
│── README_WINDOWS.md
│── APPROACH.md
```

---

## Features

- Upload Markdown documents as multiple versions
- Automatic version tracking
- Search document headings and content
- View section-level changes between versions
- Create version-pinned selections
- Generate QA test cases using an LLM
- Detect stale generations after document updates
- REST API with Swagger documentation

---

## Prerequisites

- Python 3.11 or later
- PowerShell (Windows)

Verify your Python installation:

```powershell
python --version
```

---

## Installation

Create a virtual environment.

```powershell
python -m venv .venv
```

Activate it.

```powershell
.\.venv\Scripts\Activate.ps1
```

Install all dependencies.

```powershell
pip install -r requirements.txt
```

If PowerShell blocks activation, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

or use

```powershell
.\.venv\Scripts\activate.bat
```

---

## Running the Application

Activate the virtual environment.

```powershell
.\.venv\Scripts\Activate.ps1
```

Start the FastAPI server.

```powershell
uvicorn app.main:app --reload --port 8000
```

The application will be available at:

```
http://localhost:8000
```

Swagger Documentation:

```
http://localhost:8000/docs
```

---

## Running Tests

```powershell
pytest -q
```

Expected output:

```
5 passed
```

---

## Demo Workflow

Run the server first.

Open another PowerShell window and execute:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\demo.ps1
```

The demo performs the following:

1. Upload Version 1 of the document
2. Browse document sections
3. Search for a section
4. Create a version-pinned selection
5. Generate QA test cases
6. Upload Version 2
7. Compare differences
8. Verify stale generation detection

---

## Reset Application Data

Delete the database and JSON store:

```powershell
Remove-Item ct200.db, generations.json -ErrorAction SilentlyContinue
```

---

## Environment Variables

| Variable | Description |
|-----------|-------------|
| CT200_DB | SQLite database path |
| CT200_DOCSTORE | JSON document store |
| CT200_LLM_PROVIDER | mock or groq |
| CT200_LLM_API_KEY | Groq API Key |
| CT200_LLM_MODEL | LLM model name |
| CT200_LLM_BASE_URL | Base URL for Groq |

Example:

```powershell
$env:CT200_LLM_PROVIDER="groq"
$env:CT200_LLM_API_KEY="gsk_..."
uvicorn app.main:app --port 8000
```

---

## API Endpoints

| Method | Endpoint | Description |
|---------|----------|-------------|
| POST | `/documents/{doc}/versions` | Upload a new document version |
| GET | `/documents` | List all documents |
| GET | `/documents/{doc}/sections` | View document sections |
| GET | `/nodes/{id}` | Retrieve node details |
| GET | `/search` | Search document content |
| GET | `/nodes/{id}/changes` | Compare changes across versions |
| POST | `/selections` | Create a selection |
| GET | `/selections/{id}` | Retrieve a selection |
| POST | `/selections/{id}/generate` | Generate QA test cases |
| GET | `/generations/{id}` | Retrieve generation with staleness report |

---

## Notes

- SQLite tables are created automatically on startup.
- A mock LLM provider is enabled by default.
- To use Groq, configure the required environment variables.
- The application supports document versioning and traceability across updates.

---

