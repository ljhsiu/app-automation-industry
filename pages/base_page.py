"""
App UI Automation Test Project
Base page class for Page Object Model
"""
from abc import ABC, abstractmethod


class BasePage(ABC):
    """Base page class for all page objects"""

    def __init__(self, driver):
        """
        Initialize base page
        
        Args:
            driver: ATX driver instance (u2 for Android or wda for iOS)
        """
        self.driver = driver

    @abstractmethod
    def wait_page_loaded(self, timeout=10):
        """
        Wait for page to be fully loaded
        
        Args:
            timeout: Maximum wait time in seconds
            
        Returns:
            bool: True if page loaded, False otherwise
        """
        pass

    def take_screenshot(self, name, save_dir="screenshots"):
        """
        Take screenshot and save to file
        
        Args:
            name: Screenshot file name prefix
            save_dir: Directory to save screenshots
            
        Returns:
            str: Full path to saved screenshot
        """
        import os
        import time
        
        os.makedirs(save_dir, exist_ok=True)
        filename = f"{name}_{int(time.time())}.png"
        filepath = os.path.join(save_dir, filename)
        self.driver.screenshot(filepath)
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
