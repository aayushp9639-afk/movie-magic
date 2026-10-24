/**
 * Movie Magic — Main Client-Side Scripts
 * Includes Theme Toggle, Watchlist Persistence, Quick View Modal, and Keyboard Shortcuts.
 */

const WATCHLIST_STORAGE_KEY = "moviemagic_watchlist_v1";
const THEME_STORAGE_KEY = "moviemagic_theme_v1";

function getWatchlist() {
  try {
    const raw = localStorage.getItem(WATCHLIST_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch (e) {
    return [];
  }
}

function saveWatchlist(list) {
  try {
    localStorage.setItem(WATCHLIST_STORAGE_KEY, JSON.stringify(list));
  } catch (e) {
    // Ignore storage quota errors
  }
}

function showWatchlistToast(message, isAdded) {
  const container = document.getElementById("watchlistToastContainer");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = "watchlist-toast";
  const icon = document.createElement("i");
  icon.className = `bi ${isAdded ? "bi-bookmark-heart-fill text-danger" : "bi-bookmark-dash text-secondary"} fs-5`;
  const textSpan = document.createElement("span");
  textSpan.textContent = message;
  toast.appendChild(icon);
  toast.appendChild(textSpan);
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transition = "opacity 0.25s ease";
    setTimeout(() => toast.remove(), 260);
  }, 2600);
}

function syncWatchlistUI() {
  const watchlist = getWatchlist();
  const badge = document.getElementById("watchlistCountBadge");
  if (badge) {
    badge.textContent = watchlist.length;
    badge.style.display = watchlist.length > 0 ? "inline-block" : "none";
  }

  document.querySelectorAll(".js-watchlist-btn").forEach((btn) => {
    const movieId = btn.getAttribute("data-movie-id");
    const isSaved = watchlist.includes(movieId);
    btn.classList.toggle("is-saved", isSaved);
    btn.setAttribute("aria-pressed", isSaved ? "true" : "false");

    const icon = btn.querySelector("i");
    if (icon) {
      icon.className = isSaved ? "bi bi-heart-fill" : "bi bi-heart";
    }
    const label = btn.querySelector(".js-watchlist-label");
    if (label) {
      label.textContent = isSaved ? "Saved in Watchlist" : "Save to Watchlist";
    }
  });

  // If on the /watchlist page, filter visible cards
  const watchlistGrid = document.getElementById("watchlistMoviesGrid");
  const watchlistEmpty = document.getElementById("watchlistEmptyState");
  const watchlistCountText = document.getElementById("watchlistPageCount");
  if (watchlistGrid) {
    let visibleCount = 0;
    watchlistGrid.querySelectorAll(".js-watchlist-item").forEach((col) => {
      const mId = col.getAttribute("data-movie-id");
      if (watchlist.includes(mId)) {
        col.style.display = "";
        visibleCount++;
      } else {
        col.style.display = "none";
      }
    });
    if (watchlistCountText) {
      watchlistCountText.textContent = `${visibleCount} Saved ${visibleCount === 1 ? "Title" : "Titles"}`;
    }
    if (watchlistEmpty) {
      watchlistEmpty.style.display = visibleCount === 0 ? "block" : "none";
    }
  }
}

function toggleWatchlistMovie(movieId, movieTitle) {
  if (!movieId) return;
  const watchlist = getWatchlist();
  const idx = watchlist.indexOf(movieId);
  let isAdded = false;

  if (idx === -1) {
    watchlist.push(movieId);
    isAdded = true;
    showWatchlistToast(`Added "${movieTitle || "Movie"}" to your Watchlist`, true);
  } else {
    watchlist.splice(idx, 1);
    isAdded = false;
    showWatchlistToast(`Removed "${movieTitle || "Movie"}" from Watchlist`, false);
  }

  saveWatchlist(watchlist);
  syncWatchlistUI();
}

function initTheme() {
  const savedTheme = localStorage.getItem(THEME_STORAGE_KEY) || "dark";
  document.documentElement.setAttribute("data-theme", savedTheme);
  const icon = document.getElementById("themeToggleIcon");
  if (icon) {
    icon.className = savedTheme === "light" ? "bi bi-sun-fill text-warning" : "bi bi-moon-stars-fill";
  }

  const toggleBtn = document.getElementById("themeToggleBtn");
  if (toggleBtn) {
    toggleBtn.addEventListener("click", () => {
      const current = document.documentElement.getAttribute("data-theme") || "dark";
      const next = current === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      localStorage.setItem(THEME_STORAGE_KEY, next);
      if (icon) {
        icon.className = next === "light" ? "bi bi-sun-fill text-warning" : "bi bi-moon-stars-fill";
      }
    });
  }
}

document.addEventListener("DOMContentLoaded", function () {
  initTheme();
  syncWatchlistUI();

  // Delegate Watchlist button clicks
  document.body.addEventListener("click", function (e) {
    const wlBtn = e.target.closest(".js-watchlist-btn");
    if (wlBtn) {
      e.preventDefault();
      e.stopPropagation();
      const movieId = wlBtn.getAttribute("data-movie-id");
      const movieTitle = wlBtn.getAttribute("data-movie-title");
      toggleWatchlistMovie(movieId, movieTitle);
      return;
    }

    const clearWlBtn = e.target.closest("#clearWatchlistBtn");
    if (clearWlBtn) {
      e.preventDefault();
      saveWatchlist([]);
      syncWatchlistUI();
      showWatchlistToast("Cleared all saved titles from Watchlist", false);
      return;
    }

    // Delegate Quick View button clicks
    const qvBtn = e.target.closest(".js-quickview-btn");
    if (qvBtn) {
      e.preventDefault();
      e.stopPropagation();
      const modalEl = document.getElementById("quickViewModal");
      if (!modalEl) return;

      const movieId = qvBtn.getAttribute("data-movie-id") || "";
      const title = qvBtn.getAttribute("data-movie-title") || "";
      const origTitle = qvBtn.getAttribute("data-movie-original") || "";
      const category = qvBtn.getAttribute("data-movie-category") || "";
      const rating = qvBtn.getAttribute("data-movie-rating") || "";
      const imdb = qvBtn.getAttribute("data-movie-imdb") || "";
      const year = qvBtn.getAttribute("data-movie-year") || "";
      const duration = qvBtn.getAttribute("data-movie-duration") || "";
      const language = qvBtn.getAttribute("data-movie-language") || "";
      const genre = qvBtn.getAttribute("data-movie-genre") || "";
      const director = qvBtn.getAttribute("data-movie-director") || "";
      const cast = qvBtn.getAttribute("data-movie-cast") || "";
      const synopsis = qvBtn.getAttribute("data-movie-synopsis") || "";
      const poster = qvBtn.getAttribute("data-movie-poster") || "";
      const url = qvBtn.getAttribute("data-movie-url") || "#";

      document.getElementById("quickViewModalLabel").textContent = title;
      document.getElementById("qvOriginalTitle").textContent = origTitle ? `"${origTitle}"` : "";
      document.getElementById("qvCategoryBadge").textContent = category;
      document.getElementById("qvRatingBadge").textContent = rating;
      document.getElementById("qvImdbBadge").textContent = `⭐ ${imdb}`;
      document.getElementById("qvYear").textContent = year;
      document.getElementById("qvDuration").textContent = duration;
      document.getElementById("qvLanguage").textContent = language;
      document.getElementById("qvGenre").textContent = genre;
      document.getElementById("qvDirector").textContent = director;
      document.getElementById("qvCast").textContent = cast;
      document.getElementById("qvSynopsis").textContent = synopsis;
      document.getElementById("qvDetailLink").setAttribute("href", url);

      const posterImg = document.getElementById("qvPosterImg");
      if (posterImg) {
        posterImg.src = poster;
        posterImg.alt = title;
      }

      const qvWlBtn = document.getElementById("qvWatchlistBtn");
      if (qvWlBtn) {
        qvWlBtn.className = "btn btn-outline-cinematic btn-sm px-3 js-watchlist-btn";
        qvWlBtn.setAttribute("data-movie-id", movieId);
        qvWlBtn.setAttribute("data-movie-title", title);
        qvWlBtn.innerHTML = `<i class="bi bi-heart me-1"></i> <span class="js-watchlist-label">Save to Watchlist</span>`;
        syncWatchlistUI();
      }

      const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
      modal.show();
    }
  });

  // Keyboard shortcut: press '/' to focus search input when not typing in an input
  document.addEventListener("keydown", function (e) {
    if (
      e.key === "/" &&
      !["INPUT", "TEXTAREA", "SELECT"].includes((document.activeElement || {}).tagName)
    ) {
      const searchInput = document.querySelector('input[name="q"]');
      if (searchInput) {
        e.preventDefault();
        searchInput.focus();
      }
    }
  });

  // Auto-dismiss alert toasts after 5 seconds
  const alerts = document.querySelectorAll(".alert-dismissible");
  alerts.forEach(function (alert) {
    setTimeout(function () {
      const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
      if (bsAlert) {
        bsAlert.close();
      }
    }, 5000);
  });

  // Enable Bootstrap tooltips if any
  const tooltipTriggerList = [].slice.call(
    document.querySelectorAll('[data-bs-toggle="tooltip"]')
  );
  tooltipTriggerList.map(function (tooltipTriggerEl) {
    return new bootstrap.Tooltip(tooltipTriggerEl);
  });
});
