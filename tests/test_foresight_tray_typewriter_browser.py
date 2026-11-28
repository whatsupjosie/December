"""Exercise the Counter's file tray, the embedded typewriter and the file's own save path."""
import pytest

from tests.test_2i_hosted_layout import reach
from tests.test_foresight_counter_layout_host import _signed_in_counter

sync_api = pytest.importorskip("playwright.sync_api")


def test_tray_typewriter_preserves_the_original_and_reopens_the_edit(reach):
    with sync_api.sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(args=["--no-sandbox", "--disable-3d-apis"])
        except sync_api.Error as exc:
            if "Executable doesn't exist" in str(exc):
                pytest.skip("Chromium is not installed")
            raise
        try:
            _, page = _signed_in_counter(browser, *reach)
            page.get_by_role("button", name="File", exact=True).click()
            with page.expect_file_chooser() as picker:
                page.get_by_role("menuitem", name="A file from this computer").click()
            with page.expect_event("framenavigated", predicate=lambda frame: "/writers-room?file=" in frame.url) as opened:
                picker.value.set_files({"name": "rehearsal.txt", "mimeType": "text/plain", "buffer": b"Cue"})
            tray = opened.value
            tray.wait_for_function("window.foresightFileSession && soloTextarea.value === 'Cue'")
            page.evaluate("window.__counter.fullScreen(window.__counter.trays[0])")
            tray.get_by_label("Writing presentation").select_option("typewriter")
            keyboard = tray.frame_locator("#twoiTypewriterConsole")
            keyboard.locator('[data-key-char="A"]').first.click()
            tray.wait_for_function("soloTextarea.value === 'aCue' || soloTextarea.value === 'Cuea'")
            editor = tray.locator("#soloTextarea")
            edited = editor.input_value()
            editor.press("Control+s")
            tray.wait_for_function("!foresightFileSession.pending()")
            file_id = tray.evaluate("new URLSearchParams(location.search).get('file')")
            original, draft = page.evaluate("""async id => {
                const record = await ForesightFiles.record(id);
                return [await record.original.text(), record.draft];
            }""", file_id)
            assert original == "Cue"
            assert draft == edited
            with tray.expect_navigation():
                tray.evaluate("location.reload()")
            tray.wait_for_function("!!window.foresightFileSession")
            assert editor.input_value() == edited
        finally:
            browser.close()
