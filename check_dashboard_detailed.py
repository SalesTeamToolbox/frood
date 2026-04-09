import asyncio

from playwright.async_api import async_playwright


async def check_dashboard_detailed():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        # Capture network requests
        network_requests = []

        def handle_request(request):
            network_requests.append(
                {"url": request.url, "method": request.method, "headers": dict(request.headers)}
            )

        def handle_response(response):
            network_requests.append(
                {"url": response.url, "status": response.status, "method": response.request.method}
            )

        page.on("request", handle_request)
        page.on("response", handle_response)

        # Navigate to the dashboard
        await page.goto("http://localhost:8000")

        # Wait for the page to load
        await page.wait_for_timeout(5000)

        # Try to login (using default credentials)
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

        # Check the API keys endpoint response
        api_keys_request = None
        for req in network_requests:
            if "/api/settings/keys" in req["url"]:
                api_keys_request = req
                break

        if api_keys_request:
            print(f"API keys request: {api_keys_request}")
        else:
            print("API keys request not found")

        # Get all input fields and their properties
        input_fields = await page.query_selector_all('input[type="password"]')
        print(f"Total password fields: {len(input_fields)}")

        for i, field in enumerate(input_fields):
            is_disabled = await field.is_disabled()
            field_id = await field.get_attribute("id")
            field_name = await field.get_attribute("name")
            placeholder = await field.get_attribute("placeholder")
            print(
                f"Field {i + 1}: ID={field_id}, Name={field_name}, Disabled={is_disabled}, Placeholder={placeholder}"
            )

        # Check for JavaScript errors
        js_errors = []

        def handle_console(msg):
            if msg.type == "error":
                js_errors.append(msg.text)

        page.on("console", handle_console)
        await page.wait_for_timeout(1000)

        if js_errors:
            print("JavaScript errors:")
            for error in js_errors:
                print(f"  {error}")
        else:
            print("No JavaScript errors")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(check_dashboard_detailed())
