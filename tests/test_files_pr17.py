"""
tests/test_files_pr17.py — PR 17: File manager premium.

Covers:
A) /files/list improvements
   - returns mtime and total fields
   - sort by name (default, dirs first)
   - sort by size descending
   - sort by mtime
   - filter_type=audio returns only audio entries
   - filter_type=dir returns only directories
   - access denied for path outside roots
   - 404 for non-existent path

B) /files/mkdir
   - creates directory successfully
   - returns path in response
   - rejects missing name/path
   - rejects invalid name (empty after secure_filename)

C) /files/delete
   - deletes a single file, returns deleted=1
   - partial success on mixed valid/invalid paths
   - rejects path outside roots (Access Denied)
   - returns errors list when file not found

D) /files/rename
   - renames file successfully
   - returns new_path in response
   - rejects missing params
   - rejects conflict (target already exists) -> 409
   - rejects source outside roots -> 403
   - rejects non-existent source -> 404

E) /files/copy (job-based)
   - returns job dict with job_id
   - rejects missing sources or destination
   - rejects destination outside roots

F) /files/move (job-based)
   - returns job dict with job_id
   - rejects missing sources or destination

G) /files/compress (job-based)
   - returns job dict with job_id
   - accepts paths or sources param
   - rejects missing data

H) /files/uncompress (job-based)
   - returns job dict with job_id
   - rejects non-existent archive
   - rejects missing destination

I) /files/details
   - returns metadata fields (name, size, mtime, type, readable, writable)
   - returns children_count for directories
   - rejects access outside roots -> 403
   - 404 for non-existent path

J) Upload flow (/files/upload/init, /files/upload/chunk, /files/upload/finalize)
   - init returns session_id and chunk_size
   - chunk stores data
   - finalize moves file to destination
   - init rejects missing filename
   - chunk rejects unknown session_id
   - finalize rejects unknown session_id

K) Worker helpers (_run_copy, _run_move, _run_compress, _run_uncompress)
   - _run_compress creates a valid zip
   - _run_uncompress rejects path traversal member
   - _run_uncompress handles bad zip
   - _run_copy handles missing source gracefully
   - _run_move handles missing source gracefully

L) event_log integration
   - delete failure logs event
   - rename failure logs event
"""

import io
import os
import sys
import tempfile
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_root(tmp_path):
    """A temporary directory registered as an allowed FILE_MANAGER_ROOT."""
    import config as cfg
    root = str(tmp_path)
    original = list(cfg.FILE_MANAGER_ROOTS)
    original_default = cfg.FILE_MANAGER_DEFAULT_PATH
    cfg.FILE_MANAGER_ROOTS = [root]
    cfg.FILE_MANAGER_DEFAULT_PATH = root
    yield root
    cfg.FILE_MANAGER_ROOTS = original
    cfg.FILE_MANAGER_DEFAULT_PATH = original_default


@pytest.fixture()
def files_app(tmp_root):
    """Minimal Flask app with files_bp registered, using tmp_root as allowed root."""
    from flask import Flask
    from flask_cors import CORS
    from core.extensions import socketio
    from core.state import jobs_state
    from api.files import files_bp

    jobs_state.clear()
    flask_app = Flask(__name__)
    flask_app.secret_key = "test-secret"
    flask_app.config["TESTING"] = True
    flask_app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024
    CORS(flask_app)
    flask_app.register_blueprint(files_bp, url_prefix="/api")
    socketio.init_app(flask_app, async_mode="threading")
    yield flask_app
    jobs_state.clear()


@pytest.fixture()
def client(files_app):
    with files_app.test_client() as c:
        yield c


# ─── A) /files/list ──────────────────────────────────────────────────────────

def test_list_returns_mtime_and_total(client, tmp_root):
    (open(os.path.join(tmp_root, "a.mp3"), "w")).close()
    rv = client.get(f"/api/files/list?path={tmp_root}")
    assert rv.status_code == 200
    d = rv.get_json()
    assert "total" in d
    assert d["total"] >= 1
    entry = d["entries"][0]
    assert "mtime" in entry
    assert isinstance(entry["mtime"], int)


def test_list_dirs_always_first(client, tmp_root):
    os.mkdir(os.path.join(tmp_root, "zdir"))
    open(os.path.join(tmp_root, "afile.txt"), "w").close()
    rv = client.get(f"/api/files/list?path={tmp_root}&sort=name&order=asc")
    entries = rv.get_json()["entries"]
    dir_idx = next((i for i, e in enumerate(entries) if e["is_dir"]), None)
    file_idx = next((i for i, e in enumerate(entries) if not e["is_dir"]), None)
    if dir_idx is not None and file_idx is not None:
        assert dir_idx < file_idx


def test_list_sort_by_size_desc(client, tmp_root):
    p1 = os.path.join(tmp_root, "small.txt")
    p2 = os.path.join(tmp_root, "large.txt")
    with open(p1, "w") as f: f.write("hi")
    with open(p2, "w") as f: f.write("hello world!!!")
    rv = client.get(f"/api/files/list?path={tmp_root}&sort=size&order=desc")
    assert rv.status_code == 200
    entries = [e for e in rv.get_json()["entries"] if not e["is_dir"]]
    if len(entries) >= 2:
        assert entries[0]["size"] >= entries[1]["size"]


def test_list_filter_type_audio(client, tmp_root):
    open(os.path.join(tmp_root, "song.mp3"), "w").close()
    open(os.path.join(tmp_root, "doc.txt"), "w").close()
    rv = client.get(f"/api/files/list?path={tmp_root}&filter_type=audio")
    assert rv.status_code == 200
    entries = rv.get_json()["entries"]
    assert all(e["type"] == "audio" for e in entries)


def test_list_filter_type_dir(client, tmp_root):
    os.mkdir(os.path.join(tmp_root, "mydir"))
    open(os.path.join(tmp_root, "myfile.txt"), "w").close()
    rv = client.get(f"/api/files/list?path={tmp_root}&filter_type=dir")
    entries = rv.get_json()["entries"]
    assert all(e["is_dir"] for e in entries)


def test_list_folder_name_is_real_name_not_type(client, tmp_root):
    """Folder entries must expose the real folder name in 'name', not the type value."""
    # Create several folders with distinct names
    os.makedirs(os.path.join(tmp_root, "musica"))
    os.makedirs(os.path.join(tmp_root, "favole"))
    os.makedirs(os.path.join(tmp_root, "xyz_dir"))

    rv = client.get(f"/api/files/list?path={tmp_root}&filter_type=dir")
    assert rv.status_code == 200
    entries = rv.get_json()["entries"]

    dir_names = {e["name"] for e in entries}
    # The real folder names must be present
    assert "musica" in dir_names
    assert "favole" in dir_names
    assert "xyz_dir" in dir_names
    # The type value must NOT appear as a folder name
    for e in entries:
        assert e["name"] != e["type"], (
            f"Folder '{e['name']}' has name equal to its type '{e['type']}': "
            "the Nome column would show the type label instead of the real name."
        )


def test_list_folder_type_is_cartella(client, tmp_root):
    """Folder entries must have type='cartella' (not the legacy 'dir') for proper Italian UI display."""
    os.makedirs(os.path.join(tmp_root, "test_cartella"))
    open(os.path.join(tmp_root, "test_file.txt"), "w").close()

    rv = client.get(f"/api/files/list?path={tmp_root}")
    assert rv.status_code == 200
    entries = rv.get_json()["entries"]

    for e in entries:
        if e["is_dir"]:
            assert e["type"] == "cartella", (
                f"Directory entry should have type='cartella', got type='{e['type']}'"
            )
        else:
            assert e["type"] != "cartella"


def test_list_access_denied_outside_roots(client, tmp_root):
    rv = client.get("/api/files/list?path=/etc")
    assert rv.status_code == 403


def test_list_404_non_existent(client, tmp_root):
    rv = client.get(f"/api/files/list?path={tmp_root}/nonexistent")
    assert rv.status_code == 404


# ─── B) /files/mkdir ─────────────────────────────────────────────────────────

def test_mkdir_creates_dir(client, tmp_root):
    rv = client.post("/api/files/mkdir", json={"path": tmp_root, "name": "newdir"})
    assert rv.status_code == 200
    d = rv.get_json()
    assert d["status"] == "ok"
    assert "path" in d
    assert os.path.isdir(d["path"])


def test_mkdir_rejects_missing_params(client, tmp_root):
    rv = client.post("/api/files/mkdir", json={"path": tmp_root})
    assert rv.status_code == 400


def test_mkdir_returns_path(client, tmp_root):
    rv = client.post("/api/files/mkdir", json={"path": tmp_root, "name": "checkpath"})
    d = rv.get_json()
    assert d["path"].endswith("checkpath")


# ─── C) /files/delete ────────────────────────────────────────────────────────

def test_delete_single_file(client, tmp_root):
    p = os.path.join(tmp_root, "todelete.txt")
    open(p, "w").close()
    rv = client.post("/api/files/delete", json={"paths": [p]})
    assert rv.status_code == 200
    d = rv.get_json()
    assert d["deleted"] == 1
    assert not os.path.exists(p)


def test_delete_partial_success(client, tmp_root):
    p_real = os.path.join(tmp_root, "exists.txt")
    open(p_real, "w").close()
    rv = client.post("/api/files/delete", json={"paths": [p_real, os.path.join(tmp_root, "ghost.txt")]})
    d = rv.get_json()
    assert d["deleted"] == 1
    assert len(d["errors"]) == 1
    assert d["status"] == "partial"


def test_delete_access_denied_outside_root(client, tmp_root):
    rv = client.post("/api/files/delete", json={"paths": ["/etc/passwd"]})
    d = rv.get_json()
    assert d["deleted"] == 0
    assert any(e["error"] == "Access Denied" for e in d["errors"])


def test_delete_empty_paths_returns_400(client, tmp_root):
    rv = client.post("/api/files/delete", json={"paths": []})
    assert rv.status_code == 400


# ─── D) /files/rename ────────────────────────────────────────────────────────

def test_rename_file(client, tmp_root):
    src = os.path.join(tmp_root, "old.txt")
    open(src, "w").close()
    rv = client.post("/api/files/rename", json={"path": src, "new_name": "new.txt"})
    assert rv.status_code == 200
    d = rv.get_json()
    assert d["status"] == "ok"
    assert "new_path" in d
    assert os.path.exists(d["new_path"])
    assert not os.path.exists(src)


def test_rename_conflict_409(client, tmp_root):
    src = os.path.join(tmp_root, "file1.txt")
    dst = os.path.join(tmp_root, "file2.txt")
    open(src, "w").close()
    open(dst, "w").close()
    rv = client.post("/api/files/rename", json={"path": src, "new_name": "file2.txt"})
    assert rv.status_code == 409


def test_rename_missing_params(client, tmp_root):
    rv = client.post("/api/files/rename", json={"path": os.path.join(tmp_root, "x.txt")})
    assert rv.status_code == 400


def test_rename_access_denied(client, tmp_root):
    rv = client.post("/api/files/rename", json={"path": "/etc/hosts", "new_name": "hacked"})
    assert rv.status_code == 403


def test_rename_not_found(client, tmp_root):
    rv = client.post("/api/files/rename",
                     json={"path": os.path.join(tmp_root, "nofile.txt"), "new_name": "new.txt"})
    assert rv.status_code == 404


# ─── E) /files/copy (job-based) ──────────────────────────────────────────────

def test_copy_returns_job(client, tmp_root):
    src = os.path.join(tmp_root, "tosend.txt")
    open(src, "w").close()
    dst_dir = os.path.join(tmp_root, "destcopy")
    os.mkdir(dst_dir)
    rv = client.post("/api/files/copy", json={"sources": [src], "destination": dst_dir})
    assert rv.status_code == 200
    d = rv.get_json()
    assert d["status"] == "ok"
    assert "job" in d
    assert "job_id" in d["job"]


def test_copy_missing_sources(client, tmp_root):
    rv = client.post("/api/files/copy", json={"destination": tmp_root})
    assert rv.status_code == 400


def test_copy_destination_outside_roots(client, tmp_root):
    src = os.path.join(tmp_root, "f.txt")
    open(src, "w").close()
    rv = client.post("/api/files/copy", json={"sources": [src], "destination": "/etc"})
    assert rv.status_code == 400


# ─── F) /files/move (job-based) ──────────────────────────────────────────────

def test_move_returns_job(client, tmp_root):
    src = os.path.join(tmp_root, "tomove.txt")
    open(src, "w").close()
    dst_dir = os.path.join(tmp_root, "destmove")
    os.mkdir(dst_dir)
    rv = client.post("/api/files/move", json={"sources": [src], "destination": dst_dir})
    assert rv.status_code == 200
    d = rv.get_json()
    assert "job" in d
    assert d["job"]["type"] == "file_move"


def test_move_missing_destination(client, tmp_root):
    src = os.path.join(tmp_root, "x.txt")
    open(src, "w").close()
    rv = client.post("/api/files/move", json={"sources": [src]})
    assert rv.status_code == 400


# ─── G) /files/compress (job-based) ─────────────────────────────────────────

def test_compress_returns_job(client, tmp_root):
    p = os.path.join(tmp_root, "tozip.txt")
    open(p, "w").close()
    rv = client.post("/api/files/compress", json={
        "paths": [p],
        "destination": tmp_root,
        "archive_name": "test_archive",
    })
    assert rv.status_code == 200
    d = rv.get_json()
    assert d["job"]["type"] == "file_compress"


def test_compress_accepts_sources_param(client, tmp_root):
    p = os.path.join(tmp_root, "tozip2.txt")
    open(p, "w").close()
    rv = client.post("/api/files/compress", json={
        "sources": [p],
        "destination": tmp_root,
        "archive_name": "archive2",
    })
    assert rv.status_code == 200
    assert "job" in rv.get_json()


def test_compress_missing_destination(client, tmp_root):
    rv = client.post("/api/files/compress", json={"paths": [os.path.join(tmp_root, "f.txt")]})
    assert rv.status_code == 400


# ─── H) /files/uncompress (job-based) ────────────────────────────────────────

def test_uncompress_returns_job(client, tmp_root):
    archive = os.path.join(tmp_root, "test.zip")
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("hello.txt", "hello world")
    rv = client.post("/api/files/uncompress", json={
        "path": archive,
        "destination": tmp_root,
    })
    assert rv.status_code == 200
    d = rv.get_json()
    assert d["job"]["type"] == "file_uncompress"


def test_uncompress_nonexistent_archive(client, tmp_root):
    rv = client.post("/api/files/uncompress", json={
        "path": os.path.join(tmp_root, "ghost.zip"),
        "destination": tmp_root,
    })
    assert rv.status_code == 400


def test_uncompress_missing_destination(client, tmp_root):
    archive = os.path.join(tmp_root, "a.zip")
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("f.txt", "x")
    rv = client.post("/api/files/uncompress", json={"path": archive})
    assert rv.status_code == 400


# ─── I) /files/details ───────────────────────────────────────────────────────

def test_details_file(client, tmp_root):
    p = os.path.join(tmp_root, "detail.txt")
    open(p, "w").close()
    rv = client.post("/api/files/details", json={"path": p})
    assert rv.status_code == 200
    d = rv.get_json()
    for field in ("name", "size", "mtime", "type", "readable", "writable", "path"):
        assert field in d, f"Manca campo: {field}"
    assert d["name"] == "detail.txt"


def test_details_directory(client, tmp_root):
    d_path = os.path.join(tmp_root, "adir")
    os.mkdir(d_path)
    rv = client.post("/api/files/details", json={"path": d_path})
    assert rv.status_code == 200
    d = rv.get_json()
    assert d["is_dir"] is True
    assert "children_count" in d


def test_details_access_denied(client, tmp_root):
    rv = client.post("/api/files/details", json={"path": "/root"})
    assert rv.status_code == 403


def test_details_not_found(client, tmp_root):
    rv = client.post("/api/files/details", json={"path": os.path.join(tmp_root, "ghost.txt")})
    assert rv.status_code == 404


def test_details_missing_path(client, tmp_root):
    rv = client.post("/api/files/details", json={})
    assert rv.status_code == 400


# ─── J) Upload flow ───────────────────────────────────────────────────────────

def test_upload_init_returns_session_id(client, tmp_root):
    rv = client.post("/api/files/upload/init", json={
        "filename": "test.txt",
        "total_size": 100,
        "path": tmp_root,
        "chunk_size": 1024,
    })
    assert rv.status_code == 200
    d = rv.get_json()
    assert "session_id" in d
    assert d["filename"] == "test.txt"
    assert "chunk_size" in d


def test_upload_full_flow(client, tmp_root):
    content = b"hello world content"

    # init
    rv = client.post("/api/files/upload/init", json={
        "filename": "upload_test.txt",
        "total_size": len(content),
        "path": tmp_root,
    })
    assert rv.status_code == 200
    session_id = rv.get_json()["session_id"]

    # chunk
    form_data = {
        "session_id": session_id,
        "offset": "0",
        "chunk": (io.BytesIO(content), "upload_test.txt"),
    }
    rv = client.post("/api/files/upload/chunk", data=form_data,
                     content_type="multipart/form-data")
    assert rv.status_code == 200
    assert rv.get_json()["received"] == len(content)

    # finalize
    rv = client.post("/api/files/upload/finalize", json={"session_id": session_id})
    assert rv.status_code == 200
    d = rv.get_json()
    assert d["status"] == "ok"
    assert os.path.exists(d["path"])
    assert open(d["path"], "rb").read() == content


def test_upload_init_missing_filename(client, tmp_root):
    rv = client.post("/api/files/upload/init", json={"path": tmp_root, "total_size": 10})
    assert rv.status_code == 400


def test_upload_chunk_unknown_session(client, tmp_root):
    rv = client.post("/api/files/upload/chunk", data={
        "session_id": "nonexistent",
        "offset": "0",
        "chunk": (io.BytesIO(b"x"), "f.txt"),
    }, content_type="multipart/form-data")
    assert rv.status_code == 404


def test_upload_finalize_unknown_session(client, tmp_root):
    rv = client.post("/api/files/upload/finalize", json={"session_id": "fake-session"})
    assert rv.status_code == 404


# ─── K) Worker helpers ────────────────────────────────────────────────────────

def test_run_compress_creates_zip(tmp_path):
    from core.state import jobs_state
    from core.jobs import create_job
    from api.files import _run_compress

    jobs_state.clear()
    src = tmp_path / "src.txt"
    src.write_text("hello")
    dest = str(tmp_path)

    job = create_job("file_compress", "test")
    _run_compress(job["job_id"], [str(src)], dest, "myarchive")

    archive = tmp_path / "myarchive.zip"
    assert archive.exists()
    with zipfile.ZipFile(str(archive)) as zf:
        assert "src.txt" in zf.namelist()

    assert jobs_state[job["job_id"]]["status"] == "done"
    jobs_state.clear()


def test_run_uncompress_path_traversal_rejected(tmp_path):
    from core.state import jobs_state
    from core.jobs import create_job
    from api.files import _run_uncompress

    jobs_state.clear()
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(str(archive), "w") as zf:
        zf.writestr("../evil.txt", "pwned")

    job = create_job("file_uncompress", "test")
    dest = str(tmp_path / "safe_dest")
    os.makedirs(dest, exist_ok=True)
    _run_uncompress(job["job_id"], str(archive), dest)

    assert jobs_state[job["job_id"]]["status"] == "error"
    jobs_state.clear()


def test_run_uncompress_bad_zip(tmp_path):
    from core.state import jobs_state
    from core.jobs import create_job
    from api.files import _run_uncompress

    jobs_state.clear()
    bad_archive = tmp_path / "bad.zip"
    bad_archive.write_bytes(b"this is not a zip file at all")

    dest = str(tmp_path / "out")
    os.makedirs(dest, exist_ok=True)

    job = create_job("file_uncompress", "test")
    _run_uncompress(job["job_id"], str(bad_archive), dest)
    assert jobs_state[job["job_id"]]["status"] == "error"
    jobs_state.clear()


def test_run_copy_missing_source_sets_done(tmp_path):
    from core.state import jobs_state
    from core.jobs import create_job
    from api.files import _run_copy

    jobs_state.clear()
    dest = str(tmp_path / "dest")
    os.makedirs(dest, exist_ok=True)

    job = create_job("file_copy", "test")
    _run_copy(job["job_id"], [str(tmp_path / "ghost.txt")], dest)
    # Should finish without crash
    assert jobs_state[job["job_id"]]["status"] in ("done", "error")
    jobs_state.clear()


def test_run_move_missing_source(tmp_path):
    from core.state import jobs_state
    from core.jobs import create_job
    from api.files import _run_move

    jobs_state.clear()
    dest = str(tmp_path / "dest2")
    os.makedirs(dest, exist_ok=True)

    job = create_job("file_move", "test")
    _run_move(job["job_id"], [str(tmp_path / "notexist.txt")], dest)
    assert jobs_state[job["job_id"]]["status"] in ("done", "error")
    jobs_state.clear()


def test_run_copy_revalidates_destination(tmp_path):
    from unittest.mock import patch
    from core.state import jobs_state
    from core.jobs import create_job
    from api.files import _run_copy

    jobs_state.clear()
    src = tmp_path / "hello.txt"
    src.write_text("hello")
    dest = str(tmp_path / "dest")
    os.makedirs(dest, exist_ok=True)
    job = create_job("file_copy", "test")

    def fake_resolve(path):
        return None if path.endswith("hello.txt") else path

    with patch("api.files._resolve_safe", side_effect=fake_resolve):
        _run_copy(job["job_id"], [str(src)], dest)

    assert jobs_state[job["job_id"]]["status"] == "error"
    jobs_state.clear()


def test_run_move_revalidates_destination(tmp_path):
    from unittest.mock import patch
    from core.state import jobs_state
    from core.jobs import create_job
    from api.files import _run_move

    jobs_state.clear()
    src = tmp_path / "hello.txt"
    src.write_text("hello")
    dest = str(tmp_path / "dest")
    os.makedirs(dest, exist_ok=True)
    job = create_job("file_move", "test")

    def fake_resolve(path):
        return None if path.endswith("hello.txt") else path

    with patch("api.files._resolve_safe", side_effect=fake_resolve):
        _run_move(job["job_id"], [str(src)], dest)

    assert jobs_state[job["job_id"]]["status"] == "error"
    jobs_state.clear()


# ─── L) event_log integration ─────────────────────────────────────────────────

def test_delete_failure_logs_event(tmp_root, monkeypatch):
    """If delete raises, log_event is called with area='files'."""
    from unittest.mock import patch, call
    import api.files as files_mod

    src = os.path.join(tmp_root, "fail.txt")
    open(src, "w").close()

    def fake_remove(p):
        raise OSError("permission denied")

    with patch.object(files_mod, "log_event") as mock_log_event, \
         patch("os.remove", fake_remove):
        from flask import Flask
        from flask_cors import CORS
        from core.extensions import socketio
        flask_app = Flask(__name__)
        flask_app.secret_key = "test"
        flask_app.config["TESTING"] = True
        CORS(flask_app)
        flask_app.register_blueprint(files_mod.files_bp, url_prefix="/api")
        socketio.init_app(flask_app, async_mode="threading")
        with flask_app.test_client() as tc:
            rv = tc.post("/api/files/delete", json={"paths": [src]})

    mock_log_event.assert_called()
    call_args = mock_log_event.call_args_list
    assert any(a[0][0] == "files" and a[0][1] == "error" for a in call_args)


def test_rename_failure_logs_event(tmp_root, monkeypatch):
    """If rename raises, log_event is called."""
    from core.event_log import get_events, clear_events

    clear_events()
    src = os.path.join(tmp_root, "renameme.txt")
    open(src, "w").close()

    original_rename = os.rename
    def fake_rename(a, b):
        raise OSError("rename denied")
    monkeypatch.setattr(os, "rename", fake_rename)

    from flask import Flask
    from flask_cors import CORS
    from core.extensions import socketio
    from api.files import files_bp as fb
    flask_app = Flask(__name__)
    flask_app.secret_key = "test"
    flask_app.config["TESTING"] = True
    CORS(flask_app)
    flask_app.register_blueprint(fb, url_prefix="/api")
    socketio.init_app(flask_app, async_mode="threading")

    with flask_app.test_client() as tc:
        rv = tc.post("/api/files/rename", json={"path": src, "new_name": "renamed.txt"})
    assert rv.status_code == 500

    events = get_events(limit=50)
    file_events = [e for e in events if e["area"] == "files"]
    assert len(file_events) >= 1
    clear_events()
