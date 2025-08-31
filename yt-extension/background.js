console.log("Background service worker running ✅");

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "getCookies") {
    chrome.cookies.getAll({ domain: ".youtube.com" }, (cookies) => {
      if (!cookies || cookies.length === 0) {
        console.log("⚠️ No cookies found for .youtube.com");
        sendResponse({ success: false, error: "No cookies found" });
        return;
      }

      // Generate cookies.txt format (Netscape format)
      const cookiesTxt = cookies.map(c => {
        return [
          c.domain,
          c.hostOnly ? "TRUE" : "FALSE",
          c.path,
          c.secure ? "TRUE" : "FALSE",
          c.expirationDate ? c.expirationDate : "0",
          c.name,
          c.value
        ].join("\t");
      }).join("\n");

      console.log("✅ cookies.txt generated for yt-dlp:", cookiesTxt);

      sendResponse({ success: true, cookies: cookiesTxt });
    });
    return true; // keep async channel alive
  }
});
