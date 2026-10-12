"""Four Playwright browser and API checks for UP Drive passenger ride requests."""

import json
import os
import sys
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import APIRequestContext, Browser, Playwright, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
RESULT_DIR = ROOT / "test-results"
VIDEO_DIR = RESULT_DIR / "videos"
BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:3000")


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv(ROOT / ".env")


class RideRequestE2E(unittest.TestCase):
    playwright: Playwright
    api: APIRequestContext
    browser: Browser
    token: str
    session: dict
    profile: dict
    passenger_id: str
    created_ride_id: str | None = None
    created_group_id: str | None = None
    cancelled = False
    results: list[dict] = []

    @classmethod
    def setUpClass(cls) -> None:
        email = os.getenv("E2E_PASSENGER_EMAIL")
        password = os.getenv("E2E_PASSENGER_PASSWORD")
        if not email or not password:
            raise unittest.SkipTest(
                "Set E2E_PASSENGER_EMAIL and E2E_PASSENGER_PASSWORD in .env"
            )
        RESULT_DIR.mkdir(exist_ok=True)
        VIDEO_DIR.mkdir(parents=True, exist_ok=True)
        cls.playwright = sync_playwright().start()
        cls.api = cls.playwright.request.new_context(base_url=BASE_URL)
        login = cls.api.post(
            "/api/auth/login", data={"email": email, "password": password}
        )
        if login.status != 200:
            raise RuntimeError(f"Test account login failed with HTTP {login.status}")
        payload = login.json()
        profile = payload.get("profile") or {}
        if profile.get("role") != "passenger":
            raise RuntimeError("The test account must have the passenger role")
        cls.passenger_id = profile["id"]
        cls.token = payload["session"]["access_token"]
        cls.session = payload["session"]
        cls.profile = profile
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls) -> None:
        if (
            hasattr(cls, "api")
            and hasattr(cls, "token")
            and cls.created_ride_id
            and not cls.cancelled
        ):
            try:
                cls.api.post(
                    f"/api/rides/{cls.created_ride_id}/cancel",
                    headers=cls.auth_headers(),
                )
            except Exception:
                pass
        if hasattr(cls, "api"):
            cls.api.dispose()
        if hasattr(cls, "browser"):
            cls.browser.close()
        if hasattr(cls, "playwright"):
            cls.playwright.stop()
        RESULT_DIR.mkdir(exist_ok=True)
        (RESULT_DIR / "ride-request-results.json").write_text(
            json.dumps(
                {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "base_url": BASE_URL,
                    "passenger_id": getattr(cls, "passenger_id", None),
                    "created_ride_id": cls.created_ride_id,
                    "created_group_id": cls.created_group_id,
                    "cancelled": cls.cancelled,
                    "results": cls.results,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    @classmethod
    def auth_headers(cls) -> dict[str, str]:
        return {"Authorization": f"Bearer {cls.token}"}

    def record(self, case_id: str, evidence: str) -> None:
        self.__class__.results.append(
            {"case_id": case_id, "status": "passed", "evidence": evidence}
        )

    @contextmanager
    def recorded_page(self, case_id: str):
        context = self.browser.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir=str(VIDEO_DIR),
            record_video_size={"width": 1280, "height": 720},
        )
        storage = {
            "up_drive_session": json.dumps(self.session),
            "up_drive_profile": json.dumps(self.profile),
            "UP_SUPABASE_URL": os.environ["SUPABASE_URL"],
            "UP_SUPABASE_PUBLISHABLE_KEY": os.environ["SUPABASE_PUBLISHABLE_KEY"],
        }
        context.add_init_script(
            "const items = " + json.dumps(storage) + "; "
            "for (const [key, value] of Object.entries(items)) "
            "localStorage.setItem(key, value);"
        )
        page = context.new_page()
        try:
            page.goto(f"{BASE_URL}/passenger.html", wait_until="domcontentloaded")
            page.locator("#welcome").wait_for()
            page.wait_for_function("document.querySelector('#welcome').textContent.trim().length > 0")
            yield page
            page.wait_for_timeout(900)
        finally:
            video = page.video
            context.close()
            if video:
                video.save_as(str(VIDEO_DIR / f"{case_id}.webm"))
                Path(video.path()).unlink(missing_ok=True)

    def test_01_create_ride(self) -> None:
        with self.recorded_page("TC-01") as page:
            page.locator("#origin").fill("กว๊านพะเยา")
            page.locator("#destination").fill("สถานีขนส่งพะเยา")
            page.locator("#originDetail").fill("จุดนัดพบหน้าทางเข้า")
            page.locator("#destinationDetail").fill("ประตูหลัก")
            page.locator("#targetPassengers").fill("2")
            # The map coordinates are fixed fixtures; submission still uses the real UI form.
            page.evaluate(
                "([origin, destination]) => { currentOrigin = origin; "
                "currentDestination = destination; }",
                [{"lat": 19.17, "lng": 99.9}, {"lat": 19.15, "lng": 99.91}],
            )
            with page.expect_response(
                lambda r: r.url.endswith("/api/rides") and r.request.method == "POST"
            ) as submitted:
                page.locator("#createRideButton").click()
            response = submitted.value
            self.assertEqual(response.status, 201)
            ride = response.json()["ride"]
            page.wait_for_function(
                "document.querySelector('#message').textContent.includes('สร้างรายการเดินทางเรียบร้อย')"
            )
            self.assertIn("กว๊านพะเยา", page.locator("#groupBox").inner_text())
        self.__class__.created_ride_id = ride["id"]
        self.__class__.created_group_id = ride["group_id"]
        self.assertEqual(ride["passenger_id"], self.passenger_id)
        self.assertEqual(ride["origin_text"], "กว๊านพะเยา")
        self.assertEqual(ride["destination_text"], "สถานีขนส่งพะเยา")
        self.record("TC-01", "UI created ride; HTTP 201; TC-01.webm")

    def test_02_read_created_ride(self) -> None:
        self.assertIsNotNone(self.created_ride_id, "TC-01 must create a ride first")
        with self.recorded_page("TC-02") as page:
            page.wait_for_function(
                "document.querySelector('#groupBox').textContent.includes('กว๊านพะเยา')"
            )
            self.assertIn("สถานีขนส่งพะเยา", page.locator("#groupBox").inner_text())
            response = self.api.get(
                f"/api/rides/{self.created_ride_id}", headers=self.auth_headers()
            )
            self.assertEqual(response.status, 200, response.text())
            ride = response.json()["ride"]
        self.assertEqual(ride["id"], self.created_ride_id)
        self.assertEqual(ride["passenger_id"], self.passenger_id)
        self.assertEqual(ride["origin_text"], "กว๊านพะเยา")
        self.assertEqual(ride["group_id"], self.created_group_id)
        self.record("TC-02", "UI shows saved route after reload; HTTP 200; TC-02.webm")

    def test_03_cancel_created_ride(self) -> None:
        self.assertIsNotNone(self.created_ride_id, "TC-01 must create a ride first")
        with self.recorded_page("TC-03") as page:
            button = page.locator("#groupBox button[onclick='cancelRide()']")
            button.wait_for()
            page.once("dialog", lambda dialog: dialog.accept())
            with page.expect_response(
                lambda r: r.url.endswith(f"/api/rides/{self.created_ride_id}/cancel")
            ) as submitted:
                button.click()
            self.assertEqual(submitted.value.status, 200)
            page.wait_for_function(
                "document.querySelector('#message').textContent.includes('ยกเลิกการเดินทางเรียบร้อย')"
            )
            stored = self.api.get(
                f"/api/rides/{self.created_ride_id}", headers=self.auth_headers()
            )
            self.assertEqual(stored.status, 200, stored.text())
            self.assertEqual(stored.json()["ride"]["status"], "cancelled")
        self.__class__.cancelled = True
        self.record("TC-03", "UI cancelled ride; HTTP 200; stored status cancelled; TC-03.webm")

    def test_04_reject_missing_origin(self) -> None:
        with self.recorded_page("TC-04") as page:
            page.locator("#destination").fill("สถานีขนส่งพะเยา")
            page.locator("#origin").fill("")
            page.locator("#createRideButton").click()
            self.assertTrue(
                page.locator("#origin").evaluate("element => element.validity.valueMissing")
            )
            self.assertTrue(page.locator("#origin").evaluate("element => element.validationMessage") != "")
            response = self.api.post(
                "/api/rides",
                headers=self.auth_headers(),
                data={
                    "origin_text": "",
                    "destination_text": "สถานีขนส่งพะเยา",
                    "origin_lat": 19.17,
                    "origin_lng": 99.9,
                    "destination_lat": 19.15,
                    "destination_lng": 99.91,
                    "target_passengers": 2,
                },
            )
            self.assertEqual(response.status, 400, response.text())
            self.assertIn("กรุณาระบุจุดรับ", response.json()["error"])
        self.record("TC-04", "UI required-field validation; API HTTP 400; TC-04.webm")


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RideRequestE2E)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
