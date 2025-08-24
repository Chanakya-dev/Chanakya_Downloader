console.log("Background service worker running ✅");

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "getCookies") {
    chrome.cookies.getAll({ domain: ".youtube.com" }, (cookies) => {
      if (!cookies || cookies.length === 0) {
        console.log("⚠️ No cookies found for .youtube.com");
        sendResponse({ success: false, error: "No cookies found" });
        return;
      }

      const cookieStr = cookies.map(c => `${c.name}=${c.value}`).join("; ");
      console.log("✅ Cookies fetched:", cookieStr);

      sendResponse({ success: true, cookies: cookieStr });
    });
    return true; // keep async channel alive
  }
});
