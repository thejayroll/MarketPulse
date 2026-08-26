// Firebase Config - User must replace this with their actual config from Firebase Console
const firebaseConfig = {
  apiKey: "YOUR_API_KEY",
  authDomain: "YOUR_AUTH_DOMAIN",
  projectId: "YOUR_PROJECT_ID",
  storageBucket: "YOUR_STORAGE_BUCKET",
  messagingSenderId: "YOUR_MESSAGING_SENDER_ID",
  appId: "YOUR_APP_ID"
};

// VAPID Public Key - User must replace this with their actual key from Firebase console (Cloud Messaging tab)
const VAPID_KEY = "YOUR_VAPID_PUBLIC_KEY";

let currentMode = "morning";

// Elements
const morningTab = document.getElementById("tab-morning");
const eveningTab = document.getElementById("tab-evening");
const refreshBtn = document.getElementById("refresh-btn");
const offlineBadge = document.getElementById("offline-badge");
const tokenCard = document.getElementById("token-card");
const tokenInput = document.getElementById("fcm-token-input");
const copyTokenBtn = document.getElementById("copy-token-btn");
const closeTokenBtn = document.getElementById("close-token-btn");

// Initialization
document.addEventListener("DOMContentLoaded", () => {
  setupModeByTime();
  initPwaAndFirebase();
  loadBriefing();
  setupEventListeners();
});

function setupModeByTime() {
  // Default to evening if it is after 4 PM local time
  const hour = new Date().getHours();
  if (hour >= 16) {
    currentMode = "evening";
    morningTab.classList.remove("active");
    eveningTab.classList.add("active");
  }
}

function initPwaAndFirebase() {
  // Check online status
  updateOnlineStatus();
  window.addEventListener("online", updateOnlineStatus);
  window.addEventListener("offline", updateOnlineStatus);

  // Register unified service worker
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("firebase-messaging-sw.js")
      .then((registration) => {
        console.log("Service Worker registered successfully with scope:", registration.scope);
        
        // Listen for messages from service worker (e.g. background push refresh)
        navigator.serviceWorker.addEventListener("message", (event) => {
          if (event.data && event.data.action === "refresh") {
            console.log("Push notification arrived. Auto-refreshing data...");
            loadBriefing();
          }
        });

        // Initialize Firebase if configured
        if (firebaseConfig.apiKey !== "YOUR_API_KEY") {
          firebase.initializeApp(firebaseConfig);
          const messaging = firebase.messaging();
          messaging.useServiceWorker(registration);
          
          // Request notification permissions
          requestNotificationPermission(messaging);
          
          // Listen for foreground notifications
          messaging.onMessage((payload) => {
            console.log("Foreground notification received:", payload);
            loadBriefing();
          });
        } else {
          console.log("Firebase is not configured. Register your credentials in app.js to enable push notifications.");
        }
      })
      .catch((err) => {
        console.error("Service Worker registration failed:", err);
      });
  }
}

function requestNotificationPermission(messaging) {
  Notification.requestPermission().then((permission) => {
    if (permission === "granted") {
      console.log("Notification permission granted.");
      messaging.getToken({ vapidKey: VAPID_KEY })
        .then((token) => {
          if (token) {
            tokenInput.value = token;
            tokenCard.classList.remove("hidden");
          } else {
            console.log("No registration token available. Request permission to generate one.");
          }
        })
        .catch((err) => {
          console.error("Error retrieving FCM registration token:", err);
        });
    } else {
      console.warn("Notification permission denied.");
    }
  });
}

function updateOnlineStatus() {
  if (navigator.onLine) {
    offlineBadge.classList.add("hidden");
  } else {
    offlineBadge.classList.remove("hidden");
  }
}

function setupEventListeners() {
  morningTab.addEventListener("click", () => switchMode("morning"));
  eveningTab.addEventListener("click", () => switchMode("evening"));
  refreshBtn.addEventListener("click", loadBriefing);
  
  closeTokenBtn.addEventListener("click", () => tokenCard.classList.add("hidden"));
  copyTokenBtn.addEventListener("click", () => {
    tokenInput.select();
    navigator.clipboard.writeText(tokenInput.value)
      .then(() => {
        copyTokenBtn.textContent = "Copied!";
        setTimeout(() => { copyTokenBtn.textContent = "Copy"; }, 2000);
      });
  });
}

function switchMode(mode) {
  if (currentMode === mode) return;
  currentMode = mode;
  
  if (mode === "morning") {
    morningTab.classList.add("active");
    eveningTab.classList.remove("active");
  } else {
    morningTab.classList.remove("active");
    eveningTab.classList.add("active");
  }
  loadBriefing();
}

function loadBriefing() {
  const url = `../data/latest_${currentMode}.json`;
  
  // Try network first
  fetch(url)
    .then((response) => {
      if (!response.ok) throw new Error("Network response was not ok");
      return response.json();
    })
    .then((data) => {
      // Save cache locally
      localStorage.setItem(`cached_${currentMode}`, JSON.stringify(data));
      renderBriefing(data);
    })
    .catch((err) => {
      console.warn("Fetching new briefing failed. Trying offline cache...", err);
      // Fallback to local storage cache
      const cached = localStorage.getItem(`cached_${currentMode}`);
      if (cached) {
        renderBriefing(JSON.parse(cached));
      } else {
        renderEmptyState();
      }
    });
}

function renderBriefing(data) {
  // 1. Render Hero Market Sentiment
  const marketWide = data.market_wide_sentiment || {};
  const label = marketWide.label || "neutral";
  const confidence = marketWide.confidence || 0.0;
  
  const hero = document.getElementById("sentiment-hero");
  const heroLabel = document.getElementById("market-sentiment-label");
  const heroConf = document.getElementById("market-sentiment-conf");
  const heroTime = document.getElementById("briefing-time");
  
  // Clean classes
  hero.className = "card sentiment-hero";
  hero.classList.add(`theme-${label}-bg`);
  heroLabel.className = "sentiment-text";
  heroLabel.classList.add(`theme-${label}`);
  
  heroLabel.textContent = label;
  heroConf.textContent = `Confidence: ${Math.round(confidence * 100)}%`;
  
  if (data.timestamp) {
    const d = new Date(data.timestamp);
    heroTime.textContent = `As of ${d.toLocaleDateString()} ${d.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}`;
  } else {
    heroTime.textContent = "-";
  }

  // 2. Render Evening Movers
  const moversSection = document.getElementById("evening-movers-section");
  if (currentMode === "evening") {
    moversSection.classList.remove("hidden");
    
    const gTable = document.querySelector("#gainers-table tbody");
    const lTable = document.querySelector("#losers-table tbody");
    const accNote = document.getElementById("evening-accuracy-note");
    
    gTable.innerHTML = (data.top_gainers || []).map(g => 
      `<tr><td>${g.ticker.replace(".NS", "")}</td><td>${g.change}</td></tr>`
    ).join("") || "<tr><td colspan='2'>No gainers data.</td></tr>";
    
    lTable.innerHTML = (data.top_losers || []).map(l => 
      `<tr><td>${l.ticker.replace(".NS", "")}</td><td>${l.change}</td></tr>`
    ).join("") || "<tr><td colspan='2'>No losers data.</td></tr>";
    
    accNote.textContent = data.accuracy_note || "";
  } else {
    moversSection.classList.add("hidden");
  }

  // 3. Render Watchlist
  const watchlistContainer = document.getElementById("watchlist-container");
  const watchlist = data.watchlist || [];
  
  if (watchlist.length > 0) {
    watchlistContainer.innerHTML = watchlist.map((w) => {
      const tickerName = w.ticker.replace(".NS", "");
      const sentClass = `theme-${w.sentiment}`;
      const signalsHtml = (w.top_signals || []).map(s => 
        `<span class="sig-pill">${s}</span>`
      ).join("");
      
      return `
        <div class="ticker-card">
          <div class="ticker-left">
            <span class="ticker-sym">${tickerName}</span>
            <span class="ticker-sent-badge ${sentClass}">${w.sentiment} (${Math.round(w.confidence * 100)}%)</span>
          </div>
          <div class="ticker-right">
            ${signalsHtml}
          </div>
        </div>
      `;
    }).join("");
  } else {
    watchlistContainer.innerHTML = `<p class="empty-state">No watchlist data found.</p>`;
  }

  // 4. Render News
  const newsContainer = document.getElementById("news-container");
  let hasNews = false;
  let newsHtml = "";
  
  watchlist.forEach((w) => {
    if (w.news && w.news.length > 0) {
      hasNews = true;
      w.news.forEach((n) => {
        newsHtml += `
          <div class="news-item">
            <a href="${n.url}" target="_blank" rel="noopener noreferrer">${n.title}</a>
            <p class="news-inference">${n.inference}</p>
          </div>
        `;
      });
    }
  });
  
  if (hasNews) {
    newsContainer.innerHTML = newsHtml;
  } else {
    newsContainer.innerHTML = `<p class="empty-state">No news mapped to watchlist.</p>`;
  }
}

function renderEmptyState() {
  document.getElementById("market-sentiment-label").textContent = "No Data";
  document.getElementById("market-sentiment-conf").textContent = "Briefing files missing or offline.";
  document.getElementById("watchlist-container").innerHTML = `<p class="empty-state">Offline and no cached data available.</p>`;
  document.getElementById("news-container").innerHTML = `<p class="empty-state">Offline and no cached news available.</p>`;
}
