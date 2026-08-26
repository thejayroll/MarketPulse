// Firebase Config - User must replace this with their actual config from Firebase Console
const firebaseConfig = {
  apiKey: "AIzaSyDawd0zsvyjMVEVdcWvECvqIBmUINqkO6Y",
  authDomain: "marketpulse-c9599.firebaseapp.com",
  projectId: "marketpulse-c9599",
  storageBucket: "marketpulse-c9599.firebasestorage.app",
  messagingSenderId: "904312621267",
  appId: "1:904312621267:web:3993d40261af6135006c26",
  measurementId: "G-23PDQM4PY2"
};

// VAPID Public Key - User must replace this with their actual key from Firebase console (Cloud Messaging tab)
const VAPID_KEY = "BAjzh3CDOgGe6xx1oMhhZKQHiqn96OTtqsXIu_deKm3pJBBkWNGLAx5CcOKYV6pNzbgEXWuPEFUa5FEKKnfL3A4";

const PATTERN_EXPLANATIONS = {
  "double top": "Bearish reversal pattern indicating price failed twice to break resistance, suggesting a downward reversal.",
  "double bottom": "Bullish reversal pattern indicating price found support twice, suggesting a potential upward reversal.",
  "head and shoulders": "Bearish reversal indicating an uptrend is losing strength and a downward trend is starting.",
  "inverse head and shoulders": "Bullish reversal indicating a downtrend is exhausting and a new upward trend is beginning.",
  "ascending triangle": "Bullish consolidation pattern indicating buyers are aggressive, suggesting a breakout to the upside.",
  "descending triangle": "Bearish consolidation pattern indicating sellers are dominant, suggesting a breakdown to the downside.",
  "symmetrical triangle": "Neutral consolidation showing compressing volatility, indicating a sharp breakout is imminent.",
  "breakout": "Price has pushed above key resistance or SMA lines, indicating strong bullish momentum.",
  "breakdown": "Price has slipped below key support or SMA lines, indicating strong bearish momentum."
};

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
  // Lock morning after 1 PM (13:00) and evening before 1 PM local time
  const hour = new Date().getHours();
  if (hour >= 13) {
    currentMode = "evening";
    morningTab.classList.remove("active");
    morningTab.disabled = true;
    morningTab.title = "Morning briefing is locked after 1:00 PM";
    eveningTab.classList.add("active");
    eveningTab.disabled = false;
  } else {
    currentMode = "morning";
    eveningTab.classList.remove("active");
    eveningTab.disabled = true;
    eveningTab.title = "Evening summary is locked before 1:00 PM";
    morningTab.classList.add("active");
    morningTab.disabled = false;
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
  const hour = new Date().getHours();
  if (mode === "morning" && hour >= 13) {
    console.warn("Morning mode is locked after 1:00 PM");
    return;
  }
  if (mode === "evening" && hour < 13) {
    console.warn("Evening mode is locked before 1:00 PM");
    return;
  }
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
  
  window.tickerData = window.tickerData || {};
  
  if (watchlist.length > 0) {
    watchlistContainer.innerHTML = watchlist.map((w) => {
      const tickerName = w.ticker.replace(".NS", "");
      const sentClass = `theme-${w.sentiment}`;
      
      // Save data globally for dynamic period changes
      window.tickerData[tickerName] = {
        history: w.history || [],
        patternDates: w.pattern_dates || [],
        sentiment: w.sentiment
      };
      
      let patternText = "";
      const signalsHtml = (w.top_signals || []).map(s => {
        const lowerS = s.toLowerCase();
        if (lowerS.includes("chart pattern:")) {
          patternText = getPatternInference(s, tickerName);
          return "";
        }
        return `<span class="sig-pill">${s}</span>`;
      }).filter(html => html !== "").join("");
      
      const patternHtml = patternText ? `<div class="pattern-indicator">⚠️ ${patternText}</div>` : "";
      
      const periodSelectorHtml = (w.history && w.history.length > 0) ? `
        <div class="chart-period-selector" data-ticker="${tickerName}">
          <button class="period-btn" onclick="changeChartPeriod('${tickerName}', '1W')">1W</button>
          <button class="period-btn active" onclick="changeChartPeriod('${tickerName}', '1M')">1M</button>
          <button class="period-btn" onclick="changeChartPeriod('${tickerName}', '6M')">6M</button>
          <button class="period-btn" onclick="changeChartPeriod('${tickerName}', '1Y')">1Y</button>
          <button class="period-btn" onclick="changeChartPeriod('${tickerName}', '5Y')">5Y</button>
        </div>
      ` : "";
      
      const chartHtml = (w.history && w.history.length > 0) ? 
        `<div class="chart-container"><canvas id="chart-${tickerName}" class="ticker-chart" width="400" height="150"></canvas></div>` : "";
      
      return `
        <div class="ticker-card-wrapper" style="width: 100%; display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 20px; padding: 16px;">
          <div class="ticker-card" style="border: none; background: none; padding: 0; margin: 0; width: 100%;">
            <div class="ticker-left">
              <span class="ticker-sym">${tickerName}</span>
              <span class="ticker-sent-badge ${sentClass}">${w.sentiment} (${Math.round(w.confidence * 100)}%)</span>
            </div>
            <div class="ticker-right">
              ${signalsHtml}
            </div>
          </div>
          ${periodSelectorHtml}
          ${chartHtml}
          ${patternHtml}
        </div>
      `;
    }).join("");

    // Draw default 1M charts
    watchlist.forEach((w) => {
      const tickerName = w.ticker.replace(".NS", "");
      const canvas = document.getElementById(`chart-${tickerName}`);
      if (canvas && w.history && w.history.length > 0) {
        const filtered = filterHistoryByPeriod(w.history, "1M");
        drawStockChart(canvas, filtered, w.pattern_dates, w.sentiment, "1M");
      }
    });
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

// Global action handler for period switching
window.changeChartPeriod = function(tickerName, period) {
  const wrapper = document.querySelector(`.chart-period-selector[data-ticker="${tickerName}"]`);
  if (wrapper) {
    wrapper.querySelectorAll(".period-btn").forEach(btn => {
      if (btn.textContent === period) {
        btn.classList.add("active");
      } else {
        btn.classList.remove("active");
      }
    });
  }

  const canvas = document.getElementById(`chart-${tickerName}`);
  const tickerInfo = window.tickerData[tickerName];
  if (canvas && tickerInfo) {
    const filteredHistory = filterHistoryByPeriod(tickerInfo.history, period);
    drawStockChart(canvas, filteredHistory, tickerInfo.patternDates, tickerInfo.sentiment, period);
  }
};

function filterHistoryByPeriod(history, period) {
  if (!history || history.length === 0) return [];
  switch (period) {
    case "1W":
      return history.slice(-5);
    case "1M":
      return history.slice(-22);
    case "6M":
      return history.slice(-125);
    case "1Y":
      return history.slice(-250);
    case "5Y":
    default:
      return history;
  }
}

function getPatternInference(pattern, tickerName) {
  const pat = pattern.toLowerCase();
  if (pat.includes("double top")) {
    return `<strong>Double Top</strong> detected: ${tickerName} failed twice to break resistance at the circled peaks, indicating a strong bearish reversal.`;
  }
  if (pat.includes("double bottom")) {
    return `<strong>Double Bottom</strong> detected: ${tickerName} found support twice at the circled bottoms, indicating a strong bullish reversal.`;
  }
  if (pat.includes("head and shoulders")) {
    return `<strong>Head & Shoulders</strong> detected: The circled peaks show the trend exhausting (middle peak is head), signaling a major bearish reversal.`;
  }
  if (pat.includes("inverse head and shoulders")) {
    return `<strong>Inverse Head & Shoulders</strong> detected: The circled troughs indicate selling exhaustion, signaling a major bullish reversal.`;
  }
  if (pat.includes("ascending triangle")) {
    return `<strong>Ascending Triangle</strong> detected: Flat resistance and rising bottoms indicate buyers are aggressive, suggesting an upside breakout.`;
  }
  if (pat.includes("descending triangle")) {
    return `<strong>Descending Triangle</strong> detected: Flat support and falling tops indicate sellers are dominant, suggesting a downside breakdown.`;
  }
  if (pat.includes("breakout")) {
    return `<strong>Breakout</strong> detected: Price has broken above key resistance at the circled point, indicating strong upward momentum.`;
  }
  if (pat.includes("breakdown")) {
    return `<strong>Breakdown</strong> detected: Price has fallen below key support at the circled point, indicating strong downward momentum.`;
  }
  return `Pattern detected: Technical indicator changes at the circled area.`;
}

function drawStockChart(canvas, history, patternDates, sentiment, period) {
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  
  // Clear canvas
  ctx.clearRect(0, 0, width, height);
  
  const paddingLeft = 15;
  const paddingRight = 45; // Right alignment space for price ticks
  const paddingTop = 15;
  const paddingBottom = 20; // Bottom alignment space for dates
  
  const graphWidth = width - paddingLeft - paddingRight;
  const graphHeight = height - paddingTop - paddingBottom;
  
  // Extract prices
  const prices = history.map(h => h.close);
  const maxPrice = Math.max(...prices);
  const minPrice = Math.min(...prices);
  const priceRange = (maxPrice - minPrice) || 1.0;
  
  // 1. Draw Grid Lines (Horizontal & Vertical like trading platform charts)
  ctx.strokeStyle = "rgba(255, 255, 255, 0.04)";
  ctx.lineWidth = 1;
  
  // Horizontal grids & Price scales
  const gridCountY = 4;
  ctx.fillStyle = "#64748b";
  ctx.font = "normal 9px -apple-system, sans-serif";
  ctx.textAlign = "left";
  
  for (let i = 0; i <= gridCountY; i++) {
    const ratio = i / gridCountY;
    const y = paddingTop + ratio * graphHeight;
    const priceVal = maxPrice - ratio * priceRange;
    
    // Grid line
    ctx.beginPath();
    ctx.moveTo(paddingLeft, y);
    ctx.lineTo(width - paddingRight, y);
    ctx.stroke();
    
    // Price text on the right
    ctx.fillText(`₹${priceVal.toFixed(0)}`, width - paddingRight + 6, y + 3);
  }
  
  // Vertical grids (representing time buckets)
  const gridCountX = 4;
  for (let i = 0; i <= gridCountX; i++) {
    const ratio = i / gridCountX;
    const x = paddingLeft + ratio * graphWidth;
    
    ctx.beginPath();
    ctx.moveTo(x, paddingTop);
    ctx.lineTo(x, height - paddingBottom);
    ctx.stroke();
  }
  
  if (history.length === 0) return;
  
  // Map history to coordinates
  const points = history.map((h, i) => {
    const x = paddingLeft + (i * graphWidth) / (history.length - 1);
    const y = height - paddingBottom - ((h.close - minPrice) * graphHeight) / priceRange;
    return { x, y, date: h.date, price: h.close };
  });
  
  // 2. Stroke and Glow Color definition (Apple Dark Theme Muted Accent Lines)
  let strokeColor = "#007aff"; // Apple Blue (Neutral/Accent)
  let glowColor = "rgba(0, 122, 255, 0.05)";
  
  if (sentiment === "bullish") {
    strokeColor = "#30d158"; // Apple Green
    glowColor = "rgba(48, 209, 88, 0.05)";
  } else if (sentiment === "bearish") {
    strokeColor = "#ff453a"; // Apple Red
    glowColor = "rgba(255, 69, 58, 0.05)";
  }
  
  // Area fill under chart line
  ctx.beginPath();
  ctx.moveTo(points[0].x, height - paddingBottom);
  points.forEach(p => ctx.lineTo(p.x, p.y));
  ctx.lineTo(points[points.length - 1].x, height - paddingBottom);
  ctx.closePath();
  const grad = ctx.createLinearGradient(0, paddingTop, 0, height - paddingBottom);
  grad.addColorStop(0, glowColor);
  grad.addColorStop(1, "rgba(0, 0, 0, 0)");
  ctx.fillStyle = grad;
  ctx.fill();
  
  // Draw chart line
  ctx.beginPath();
  ctx.moveTo(points[0].x, points[0].y);
  for (let i = 1; i < points.length; i++) {
    ctx.lineTo(points[i].x, points[i].y);
  }
  ctx.strokeStyle = strokeColor;
  ctx.lineWidth = 2.0;
  ctx.lineJoin = "round";
  ctx.stroke();
  
  // 3. Draw Date Labels at the bottom
  ctx.fillStyle = "#475569";
  ctx.textAlign = "center";
  const startDate = points[0].date;
  const endDate = points[points.length - 1].date;
  const middleDate = points[Math.floor(points.length / 2)].date;
  
  // Format short dates (e.g. "12 Aug")
  function formatShortDate(dStr) {
    const parts = dStr.split("-");
    if (parts.length < 3) return dStr;
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const day = parseInt(parts[2], 10);
    const month = months[parseInt(parts[1], 10) - 1];
    return `${day} ${month}`;
  }
  
  ctx.fillText(formatShortDate(startDate), paddingLeft + 15, height - 6);
  ctx.fillText(formatShortDate(middleDate), paddingLeft + graphWidth / 2, height - 6);
  ctx.fillText(formatShortDate(endDate), width - paddingRight - 15, height - 6);
  
  // 4. Draw Pattern Coordinate Indicators (glowing amber circles)
  if (patternDates && patternDates.length > 0) {
    patternDates.forEach(d => {
      // Find if this date is inside the currently viewed period slice
      const pt = points.find(p => p.date === d);
      if (pt) {
        // Glowing halo circle
        ctx.beginPath();
        ctx.arc(pt.x, pt.y, 8, 0, 2 * Math.PI);
        ctx.fillStyle = "rgba(255, 159, 10, 0.35)"; // Apple Amber glow
        ctx.fill();
        
        // Solid center marker
        ctx.beginPath();
        ctx.arc(pt.x, pt.y, 4, 0, 2 * Math.PI);
        ctx.strokeStyle = "#ff9f0a";
        ctx.lineWidth = 1.5;
        ctx.fillStyle = "#0c1017";
        ctx.fill();
        ctx.stroke();
      }
    });
  }
}

function renderEmptyState() {
  document.getElementById("market-sentiment-label").textContent = "No Data";
  document.getElementById("market-sentiment-conf").textContent = "Briefing files missing or offline.";
  document.getElementById("watchlist-container").innerHTML = `<p class="empty-state">Offline and no cached data available.</p>`;
  document.getElementById("news-container").innerHTML = `<p class="empty-state">Offline and no cached news available.</p>`;
}
