import asyncio
import json

from playwright.async_api import async_playwright


async def check_api_keys_response():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Capture API response
        api_response = None

        def handle_response(response):
            nonlocal api_response
            if "/api/settings/keys" in response.url:
                api_response = response

        page.on("response", handle_response)

        # Navigate to the dashboard
        await page.goto("http://localhost:8000")

        # Wait for the page to load
        await page.wait_for_timeout(5000)

        # Login
        await page.fill("#login-user", "admin")
        await page.fill("#login-pass", "!@HugeRick7425")
        await page.click('button[type="submit"]')

        # Wait for login to complete
        await page.wait_for_timeout(3000)

        # Navigate to Settings > API Keys
        await page.click("text=Settings")
        await page.click("text=API Keys")

        # Wait for the API keys page to load
        await page.wait_for_timeout(3000)

        # Check if we captured the API response
        if api_response:
            try:
                response_data = await api_response.json()
                print(f"API keys response status: {api_response.status}")
                print(f"API keys response data: {json.dumps(response_data, indent=2)}")
            except Exception as e:
                print(f"Error reading API response: {e}")
                # Try to get text response
                try:
                    text_response = await api_response.text()
                    print(f"API keys response text: {text_response}")
                except Exception as e2:
                    print(f"Error reading API response text: {e2}")
        else:
            print("API keys response not captured")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(check_api_keys_response())
