"""Automated invoice download from the SIHOS hospital billing portal."""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from core.helpers import read_lines_from_file

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_INVOICE_PAGE_FORMAT: str = "A4"
_LOGIN_BUTTON_TEXT: str = "INGRESAR"
_LOGIN_URL_PATTERN: str = "**/index.php"
_USERNAME_SELECTOR: str = 'input[name="TxtLogi"]'
_PASSWORD_SELECTOR: str = 'input[name="TxtPswd"]'


class SihosDownloader:
    """Downloads invoices from the SIHOS web portal using a browser session.

    Args:
        user: SIHOS portal username.
        password: SIHOS portal password.
        base_url: Base URL of the SIHOS portal.
        hospital_nit: NIT number of the hospital.
        invoice_prefix: Document type prefix for invoices (e.g. ``"FE"``).
        invoice_id_prefix: Invoice identifier prefix (e.g. ``"FA"``).
        invoice_doc_code: SIHOS document code for invoices.
        output_dir: Directory where downloaded PDFs are saved.
    """

    def __init__(
        self,
        user: str,
        password: str,
        base_url: str,
        hospital_nit: str,
        invoice_prefix: str,
        invoice_id_prefix: str,
        invoice_doc_code: str,
        output_dir: Path,
    ) -> None:
        self._user: str = user
        self._password: str = password
        self._base_url: str = base_url
        self._hospital_nit: str = hospital_nit
        self._invoice_prefix: str = invoice_prefix
        self._invoice_id_prefix: str = invoice_id_prefix
        self._invoice_doc_code: str = invoice_doc_code
        self._output_dir: Path = output_dir

    def run_from_list(self, invoice_numbers: list[str]) -> None:
        """Download invoices from a list of invoice numbers."""
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._download_invoices(invoice_numbers)

    def run(self, list_path: str | Path) -> None:
        """Download invoices listed in a text file."""
        self._output_dir.mkdir(parents=True, exist_ok=True)
        invoice_list = read_lines_from_file(list_path)
        self._download_invoices(invoice_list)

    def run_medication_sheets(self, targets: list[tuple[str, str, str, str]], file_prefix: str) -> None:
        """Download medication sheet PDFs for the given targets.

        Args:
            targets: List of ``(invoice_number, admission, id_type, id_number)`` tuples.
            file_prefix: Prefix used in the output filename (e.g. the doc type prefix).
        """
        self._output_dir.mkdir(parents=True, exist_ok=True)
        loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._async_download_medication_sheets(targets, file_prefix))
        finally:
            loop.close()

    def _download_invoices(self, invoice_list: list[str]) -> None:
        """Open a browser session and download each invoice."""
        loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._async_download_invoices(invoice_list))
        finally:
            loop.close()

    @asynccontextmanager
    async def _browser_session(self):
        """Async context manager that yields an authenticated SIHOS page.

        Yields the page on successful login, or ``None`` if login fails.
        The browser is always closed on exit.
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context()
            page = await context.new_page()
            try:
                logger.info("Logging into SIHOS as user %s", self._user)
                await page.goto(self._base_url)
                await page.fill(_USERNAME_SELECTOR, self._user)
                await page.fill(_PASSWORD_SELECTOR, self._password)
                await page.click(f"text={_LOGIN_BUTTON_TEXT}")
                await page.wait_for_url(_LOGIN_URL_PATTERN)
            except (PlaywrightTimeoutError, PlaywrightError) as exc:
                logger.error("SIHOS login failed: %s", exc)
                await browser.close()
                yield None
                return
            try:
                yield page
            finally:
                await browser.close()

    async def _async_download_invoices(self, invoice_list: list[str]) -> None:
        """Async implementation of the browser-based invoice download."""
        async with self._browser_session() as page:
            if page is None:
                return
            for invoice_number in invoice_list:
                url = "{}/modulos/facturacion/imprifact.php?CodiDocu={}&NumeDocu={}&MostSubCeCo=1".format(
                    self._base_url.rstrip("/"),
                    self._invoice_doc_code,
                    invoice_number,
                )
                invoice_folder = self._output_dir / f"{self._invoice_id_prefix}{invoice_number}"
                invoice_folder.mkdir(parents=True, exist_ok=True)
                out_path = invoice_folder / (
                    f"{self._invoice_prefix}_{self._hospital_nit}_{self._invoice_id_prefix}{invoice_number}.pdf"
                )
                try:
                    await page.goto(url)
                    await page.pdf(path=str(out_path), format=_INVOICE_PAGE_FORMAT)
                    logger.info("Downloaded invoice %s to %s", invoice_number, out_path)
                except (PlaywrightTimeoutError, PlaywrightError) as exc:
                    logger.error("Failed to download invoice %s: %s", invoice_number, exc)

    async def _async_download_medication_sheets(
        self, targets: list[tuple[str, str, str, str]], file_prefix: str
    ) -> None:
        """Async implementation of medication sheet download."""
        async with self._browser_session() as page:
            if page is None:
                return
            for invoice_number, admission, id_type, id_number in targets:
                url = (
                    "{}/modulos/comun/medicamentos/impriconso.php?ConsAdmi={}&TipoDocu={}&NumeUsua={}&SinModu=1".format(
                        self._base_url.rstrip("/"), admission, id_type, id_number
                    )
                )
                invoice_folder = self._output_dir / f"{self._invoice_id_prefix}{invoice_number}"
                invoice_folder.mkdir(parents=True, exist_ok=True)
                out_path = invoice_folder / (
                    f"{file_prefix}_{self._hospital_nit}_{self._invoice_id_prefix}{invoice_number}.pdf"
                )
                try:
                    await page.goto(url)
                    await page.pdf(path=str(out_path), format=_INVOICE_PAGE_FORMAT)
                    logger.info("Downloaded %s → %s", invoice_number, out_path)
                except (PlaywrightTimeoutError, PlaywrightError) as exc:
                    logger.error("Failed %s: %s", invoice_number, exc)
