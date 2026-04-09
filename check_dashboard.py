import asyncio

from playwright.async_api import async_playwright


async def check_dashboard():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        # Navigate to the dashboard
        await page.goto("http://localhost:8000")

        # Wait for the page to load
        await page.wait_for_timeout(5000)

        # Try to login (using default credentials)
        # You might need to adjust these based on your setup
        await page.fill("#login-user", "admin")
        await page.fill("#login-pass", "!@HugeRick7425")  # Using the password from memory
        await page.click('button[type="submit"]')

        # Wait for login to complete
        await page.wait_for_timeout(3000)

        # Navigate to Settings > API Keys
        await page.click("text=Settings")
        await page.click("text=API Keys")

        # Wait for the API keys page to load
        await page.wait_for_timeout(3000)

        # Check if API key fields are editable
        try:
            # Check if we can find editable fields
            editable_fields = await page.query_selector_all(
                'input[type="password"]:not([disabled])'
            )
            print(f"Found {len(editable_fields)} editable API key fields")

            # Check if we can find any API key input fields
            all_fields = await page.query_selector_all('input[type="password"]')
            print(f"Found {len(all_fields)} total API key fields")

            # Check for specific provider fields
            synthetic_field = await page.query_selector("#key-SYNTHETIC_API_KEY")
            if synthetic_field:
                is_disabled = await synthetic_field.is_disabled()
                print(f"Synthetic API Key field is {'disabled' if is_disabled else 'editable'}")
            else:
                print("Synthetic API Key field not found")

            openrouter_field = await page.query_selector("#key-OPENROUTER_API_KEY")
            if openrouter_field:
                is_disabled = await openrouter_field.is_disabled()
                print(f"OpenRouter API Key field is {'disabled' if is_disabled else 'editable'}")
            else:
                print("OpenRouter API Key field not found")

            # Check for any error messages
            error_messages = await page.query_selector_all(".error, .alert, .danger")
            for error in error_messages:
                text = await error.text_content()
                print(f"Error message found: {text}")

            # Check browser console for errors
            browser_logs = []

            def handle_console(msg):
                browser_logs.append(f"{msg.type}: {msg.text}")

            page.on("console", handle_console)
            await page.wait_for_timeout(1000)

            if browser_logs:
                print("Browser console logs:")
                for log in browser_logs:
                    print(f"  {log}")
            else:
                print("No browser console logs")

            # Check network requests for errors
            network_errors = []

            def handle_response(response):
                if response.status >= 400:
                    network_errors.append(f"{response.status} {response.url}")

            page.on("response", handle_response)
            await page.wait_for_timeout(1000)

            if network_errors:
                print("Network errors:")
                for error in network_errors:
                    print(f"  {error}")
            else:
                print("No network errors")

        except Exception as e:
            print(f"Error checking dashboard: {e}")

        # Take a screenshot
        await page.screenshot(path="dashboard_screenshot.png")
        print("Screenshot saved as dashboard_screenshot.png")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(check_dashboard())
