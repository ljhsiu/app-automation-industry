"""
App Helper - Common utilities for ATX automation
"""
import time
import os
from datetime import datetime


class AppHelper:
    """Helper class for common ATX operations"""

    def __init__(self, driver):
        """
        Initialize AppHelper
        
        Args:
            driver: ATX driver instance (u2 for Android or wda for iOS)
        """
        self.driver = driver

    def take_screenshot(self, name, save_dir="screenshots"):
        """
        Take screenshot and save to file
        
        Args:
            name: Screenshot file name prefix
            save_dir: Directory to save screenshots
            
        Returns:
            str: Full path to saved screenshot
        """
        os.makedirs(save_dir, exist_ok=True)
        filename = f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        filepath = os.path.join(save_dir, filename)
        self.driver.screenshot(filepath)
        print(f"[Screenshot] Saved: {filepath}")
        return filepath

    def swipe_up(self, duration=0.5):
        """Swipe up on screen"""
        width, height = self.driver.window_size()
        x = width // 2
        self.driver.swipe(x, height * 0.8, x, height * 0.2, duration)

    def swipe_down(self, duration=0.5):
        """Swipe down on screen"""
        width, height = self.driver.window_size()
        x = width // 2
        self.driver.swipe(x, height * 0.2, x, height * 0.8, duration)

    def swipe_left(self, duration=0.5):
        """Swipe left on screen"""
        width, height = self.driver.window_size()
        y = height // 2
        self.driver.swipe(width * 0.8, y, width * 0.2, y, duration)

    def swipe_right(self, duration=0.5):
        """Swipe right on screen"""
        width, height = self.driver.window_size()
        y = height // 2
        self.driver.swipe(width * 0.2, y, width * 0.8, y, duration)

    def wait_element_exists(self, locator, timeout=10, interval=0.5):
        """
        Wait for element to exist
        
        Args:
            locator: Element locator (depends on driver type)
            timeout: Maximum wait time in seconds
            interval: Check interval in seconds
            
        Returns:
            bool: True if element exists, False otherwise
        """
        start = time.time()
        while time.time() - start < timeout:
            if locator.exists:
                return True
            time.sleep(interval)
        return False

    def click_back(self):
        """Press back button"""
        self.driver.press("back")

    def click_home(self):
        """Press home button"""
        self.driver.press("home")

    def get_toast_message(self, timeout=5):
        """
        Get toast message (Android only)
        
        Args:
            timeout: Maximum wait time in seconds
            
        Returns:
            str: Toast message text, or empty string if not found
        """
        try:
            # For uiautomator2
            if hasattr(self.driver, 'toast'):
                return self.driver.toast.get_message(timeout=timeout, default=None) or ""
        except Exception:
            pass
        return ""

    def dump_page_xml(self, save_path=None):
        """
        Dump current page XML hierarchy
        
        Args:
            save_path: Optional path to save XML file
            
        Returns:
            str: XML content
        """
        xml = self.driver.dump_hierarchy()
        if save_path:
            with open(save_path, 'w', encoding='utf-8') as f:
                f.write(xml)
        return xml
