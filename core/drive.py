"""Google Drive API client for folder search and recursive file downloads."""

import io
import logging
import time
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Drive API constants
# ---------------------------------------------------------------------------

_DRIVE_FOLDER_MIME: str = "application/vnd.google-apps.folder"
_DRIVE_SCOPES: list[str] = ["https://www.googleapis.com/auth/drive.readonly"]
_DRIVE_SEARCH_PAGE_SIZE: int = 1000
_DRIVE_FILE_BATCH_SIZE: int = 50  # max file names per batched OR-query

# Transient HTTP status codes that warrant a retry (5xx server errors + 429 rate-limit).
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_RETRIES: int = 4
_RETRY_BACKOFF_BASE: float = 2.0  # seconds; doubles on each attempt


class DriveSync:
    """Client for the Google Drive API.

    Supports global folder searches and recursive directory downloads.

    Args:
        credentials_dict: Service-account credentials as a parsed JSON dict.
    """

    def __init__(self, credentials_dict: dict) -> None:
        self.creds = service_account.Credentials.from_service_account_info(credentials_dict, scopes=_DRIVE_SCOPES)
        self.service = build("drive", "v3", credentials=self.creds)

    def _execute_with_retry(self, request) -> dict:
        """Execute a Drive API request, retrying on transient server errors."""
        delay = _RETRY_BACKOFF_BASE
        for attempt in range(_MAX_RETRIES + 1):
            try:
                return request.execute()
            except HttpError as exc:
                if exc.status_code not in _RETRYABLE_STATUS or attempt == _MAX_RETRIES:
                    raise
                logger.warning(
                    "Drive API HTTP %s — retrying in %.0fs (attempt %d/%d)…",
                    exc.status_code,
                    delay,
                    attempt + 1,
                    _MAX_RETRIES,
                )
                time.sleep(delay)
                delay *= 2
        raise RuntimeError("unreachable")  # pragma: no cover

    def find_folders_by_name(self, folder_name: str) -> list[dict]:
        """Search Drive for folders whose names contain the given string."""
        query = f"name contains '{folder_name}' and mimeType = '{_DRIVE_FOLDER_MIME}' and trashed = false"
        request = self.service.files().list(
            q=query,
            fields="files(id, name, parents)",
            pageSize=_DRIVE_SEARCH_PAGE_SIZE,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        results = self._execute_with_retry(request)
        return results.get("files", [])

    def download_file(self, file_id: str, file_name: str, local_dir: Path) -> None:
        """Download a single file from Drive to the local filesystem."""
        local_dir.mkdir(parents=True, exist_ok=True)
        file_path = local_dir / file_name

        if file_path.exists():
            logger.info("Skipping already-downloaded file: %s", file_name)
            return

        try:
            request = self.service.files().get_media(fileId=file_id)
            with io.FileIO(str(file_path), "wb") as fh:
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    _status, done = downloader.next_chunk()
            logger.info("Downloaded file: %s", file_name)
        except (OSError, HttpError) as exc:
            logger.error("Failed to download file %s: %s", file_name, exc)

    def _list_folder_contents(self, folder_id: str, page_token: str | None) -> dict:
        """Fetch one page of a Drive folder's children."""
        query = f"'{folder_id}' in parents and trashed = false"
        request = self.service.files().list(
            q=query,
            fields="nextPageToken, files(id, name, mimeType)",
            pageToken=page_token,
            pageSize=_DRIVE_SEARCH_PAGE_SIZE,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        return self._execute_with_retry(request)

    def _process_drive_item(self, item: dict, local_path: Path, depth: int) -> None:
        """Route a single Drive item to download or recurse into a sub-folder."""
        if item["mimeType"] == _DRIVE_FOLDER_MIME:
            self._sync_folder_tree(item["id"], local_path / item["name"], depth + 1)
        elif "google-apps" not in item["mimeType"]:
            self.download_file(item["id"], item["name"], local_path)
        else:
            logger.info("Skipping Google native file: %s", item["name"])

    def _sync_folder_tree(self, folder_id: str, local_path: Path, depth: int = 0) -> None:
        """Recursively download the contents of a Drive folder."""
        logger.info("Processing folder %s (depth %d)", local_path.name, depth)

        page_token: str | None = None
        has_items = False

        while True:
            results = self._list_folder_contents(folder_id, page_token)
            items = results.get("files", [])

            if items:
                has_items = True

            for item in items:
                self._process_drive_item(item, local_path, depth)

            page_token = results.get("nextPageToken")
            if not page_token:
                break

        if not has_items and depth == 0:
            logger.warning("Folder appears to be empty in Drive: %s", local_path.name)

    def _batch_search_folders(self, targets: list[str]) -> tuple[set[str], list[dict]]:
        """Search Drive for multiple folder names using batched OR-queries.

        Each chunk of up to ``_DRIVE_FILE_BATCH_SIZE`` targets is resolved in a
        single ``files.list`` call.  Results are matched back to targets via a
        case-insensitive substring check (replicating Drive's ``contains``
        semantics) and deduplicated by folder ID so each folder is downloaded
        at most once even when it matches several targets.

        Args:
            targets: Folder names to search for.

        Returns:
            ``(found_targets, unique_folders)`` where ``found_targets`` is the
            subset of *targets* that matched at least one Drive folder, and
            ``unique_folders`` is the de-duplicated list of folder dicts ready
            to download.
        """
        found_targets: set[str] = set()
        folders_by_id: dict[str, dict] = {}

        for offset in range(0, len(targets), _DRIVE_FILE_BATCH_SIZE):
            chunk = targets[offset : offset + _DRIVE_FILE_BATCH_SIZE]
            names_clause = " or ".join(f"name contains '{t}'" for t in chunk)
            query = f"({names_clause}) and mimeType = '{_DRIVE_FOLDER_MIME}' and trashed = false"
            request = self.service.files().list(
                q=query,
                fields="files(id, name)",
                pageSize=_DRIVE_SEARCH_PAGE_SIZE,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            results = self._execute_with_retry(request)

            for folder in results.get("files", []):
                folders_by_id[folder["id"]] = folder
                folder_name_lower = folder["name"].lower()
                for target in chunk:
                    if target.lower() in folder_name_lower:
                        found_targets.add(target)

        return found_targets, list(folders_by_id.values())

    def download_missing_dirs(self, dir_names: list[str], local_root: Path) -> list[str]:
        """Search Drive for a list of folder names and download each one found.

        Returns:
            Subset of *dir_names* that were found in Drive and downloaded.
        """
        if not dir_names:
            return []

        logger.info("Searching Drive for %d folder(s)", len(dir_names))
        found_targets, unique_folders = self._batch_search_folders(dir_names)

        for folder in unique_folders:
            self._sync_folder_tree(folder["id"], local_root / folder["name"])

        not_found = set(dir_names) - found_targets
        for target in sorted(not_found):
            logger.warning("Folder not found in Drive: %s", target)

        logger.info(
            "Drive download complete: %d/%d folders found",
            len(found_targets),
            len(dir_names),
        )
        return list(found_targets)

    def download_specific_files(self, requests: list[tuple[str, Path]]) -> tuple[int, int]:
        """Search for specific files by name in Drive and download them.

        Batches all file-name lookups into chunked OR-queries to minimise
        round-trips.  Each chunk issues a single ``files.list`` call and
        dispatches downloads for every match found.

        Args:
            requests: Pairs of ``(file_name, dest_folder)`` to locate and
                download.  ``dest_folder`` is created automatically if it does
                not yet exist.

        Returns:
            ``(found_count, not_found_count)`` across all requests.
        """
        if not requests:
            return 0, 0

        logger.info("Searching Drive for %d specific file(s)", len(requests))

        # file_name → dest_folder; duplicate names are not expected but the
        # last mapping wins (safe fallback).
        dest_by_name: dict[str, Path] = {name: dest for name, dest in requests}
        names = list(dest_by_name)
        found_count = 0

        for offset in range(0, len(names), _DRIVE_FILE_BATCH_SIZE):
            chunk = names[offset : offset + _DRIVE_FILE_BATCH_SIZE]
            names_clause = " or ".join(f"name = '{n}'" for n in chunk)
            query = f"({names_clause}) and mimeType != '{_DRIVE_FOLDER_MIME}' and trashed = false"
            request = self.service.files().list(
                q=query,
                fields="files(id, name)",
                pageSize=len(chunk),
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            results = self._execute_with_retry(request)

            matched_names: set[str] = set()
            for file_info in results.get("files", []):
                name = file_info["name"]
                matched_names.add(name)
                self.download_file(file_info["id"], name, dest_by_name[name])
                found_count += 1

            for name in sorted(set(chunk) - matched_names):
                logger.info("File not found in Drive: %s", name)

        not_found_count = len(requests) - found_count
        if not_found_count:
            logger.warning("%d file(s) not found in Drive", not_found_count)

        return found_count, not_found_count
