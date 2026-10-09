/* =====================================================
   SpotiSync – Frontend JavaScript
   ===================================================== */

let currentJobId = null;
let pollInterval = null;
let currentPlaylistId = null;
let allTracks = [];
let activeFilter = 'all';

// Selection state
let selectMode = false;
let selectedTracks = new Set();

// ==============================
// VIEW SWITCHING
// ==============================
function showView(view) {
  document.getElementById('viewHome').style.display = view === 'home' ? 'block' : 'none';
  document.getElementById('viewHistory').style.display = view === 'history' ? 'block' : 'none';
  document.getElementById('viewSettings').style.display = view === 'settings' ? 'block' : 'none';
  document.getElementById('navHome').classList.toggle('active', view === 'home');
  document.getElementById('navHistory').classList.toggle('active', view === 'history');
  document.getElementById('navSettings').classList.toggle('active', view === 'settings');
  if (view === 'settings') checkCookieStatus();
}

// ==============================
// CONVERSION FLOW
// ==============================
async function startConversion() {
  const url = document.getElementById('playlistUrl').value.trim();
  if (!url) {
    showToast('Please paste a Spotify playlist URL', 'error');
    return;
  }

  const btn = document.getElementById('convertBtn');
  btn.disabled = true;
  btn.querySelector('.btn-label').textContent = 'Starting...';

  // Reset UI
  document.getElementById('progressCard').style.display = 'block';
  document.getElementById('resultsSection').style.display = 'none';
  document.getElementById('liveFeed').innerHTML = '';
  document.getElementById('progressBarFill').style.width = '0%';
  document.getElementById('progressStatus').textContent = 'Connecting to Spotify...';
  document.getElementById('progressCount').textContent = '';

  try {
    const res = await fetch('/api/process', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url })
    });

    if (res.status === 401) {
      const data = await res.json();
      document.getElementById('progressCard').style.display = 'none';
      btn.disabled = false;
      btn.querySelector('.btn-label').textContent = 'Convert';
      showToast('Session expired — please reconnect Spotify', 'error');
      setTimeout(() => { window.location.href = '/login'; }, 1500);
      return;
    }

    const data = await res.json();
    if (data.error) throw new Error(data.error);

    currentJobId = data.job_id;
    allTracks = [];
    pollProgress();
  } catch (err) {
    showToast(`Error: ${err.message}`, 'error');
    document.getElementById('progressCard').style.display = 'none';
    btn.disabled = false;
    btn.querySelector('.btn-label').textContent = 'Convert';
  }
}


function pollProgress() {
  if (pollInterval) clearInterval(pollInterval);
  pollInterval = setInterval(async () => {
    try {
      const res = await fetch(`/api/status/${currentJobId}`);
      const job = await res.json();
      updateProgress(job);

      if (job.status === 'done' || job.status === 'error') {
        clearInterval(pollInterval);
        const btn = document.getElementById('convertBtn');
        btn.disabled = false;
        btn.querySelector('.btn-label').textContent = 'Convert';

        if (job.status === 'done') {
          showResults(job);
          showToast(`✅ Done! Found ${job.tracks.filter(t => t.status === 'found').length} / ${job.total} songs`, 'success');
        } else {
          showToast(`Error: ${job.error}`, 'error');
        }
      }
    } catch (e) {
      console.error('Poll error:', e);
    }
  }, 1000);
}

function updateProgress(job) {
  const statusMap = {
    fetching_spotify: '🎵 Fetching playlist from Spotify...',
    searching_ytmusic: '🔍 Searching YouTube Music...',
    done: '✅ Complete!',
    error: '❌ Error'
  };

  document.getElementById('progressStatus').textContent = statusMap[job.status] || job.status;

  if (job.total > 0) {
    document.getElementById('progressCount').textContent = `${job.progress} / ${job.total}`;
    document.getElementById('progressBarFill').style.width = `${(job.progress / job.total) * 100}%`;
  }

  if (job.playlist_name) {
    document.getElementById('progressPlaylistName').textContent = `📀 ${job.playlist_name}`;
  }

  // Append new live feed items
  const feed = document.getElementById('liveFeed');
  const newItems = job.tracks.slice(allTracks.length);
  newItems.forEach(track => {
    const item = document.createElement('div');
    item.className = `feed-item ${track.status}`;
    item.innerHTML = `
      <span class="feed-icon">${track.status === 'found' ? '✅' : '❌'}</span>
      <span class="feed-name">${escHtml(track.name)} – ${escHtml(track.artist_string)}</span>
      <span class="feed-status">${track.status === 'found' ? 'Found' : 'Not found'}</span>
    `;
    feed.appendChild(item);
    feed.scrollTop = feed.scrollHeight;
  });
  allTracks = [...job.tracks];
}

// ==============================
// SHOW RESULTS
// ==============================
function showResults(job) {
  currentPlaylistId = job.playlist_id;
  const section = document.getElementById('resultsSection');
  section.style.display = 'block';

  const found = allTracks.filter(t => t.status === 'found').length;
  document.getElementById('resultsTitle').textContent = job.playlist_name || 'Results';
  document.getElementById('resultsSubtitle').textContent =
    `${allTracks.length} tracks · ${found} found on YouTube Music · ${allTracks.length - found} not found`;

  renderTracks(allTracks);
  section.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderTracks(tracks) {
  const grid = document.getElementById('tracksGrid');
  grid.innerHTML = '';

  if (!tracks.length) {
    grid.innerHTML = '<div class="empty-state"><div class="empty-icon">🎵</div><div class="empty-text">No tracks match your filter</div></div>';
    return;
  }

  tracks.forEach((track, i) => {
    const card = document.createElement('div');
    card.className = 'track-card';
    card.style.animationDelay = `${Math.min(i * 0.04, 1)}s`;

    const artHtml = track.album_art
      ? `<img src="${escHtml(track.album_art)}" class="track-art" alt="Album art" loading="lazy" />`
      : `<div class="track-art-placeholder">🎵</div>`;

    const checkboxHtml = `<div class="track-checkbox" style="display: ${selectMode ? 'block' : 'none'}; position: absolute; top: 10px; left: 10px; z-index: 10;">
        <input type="checkbox" onchange="toggleTrackSelect(this, '${escHtml(track.youtube_music_url || track.youtube_url)}')" ${selectedTracks.has(track.youtube_music_url || track.youtube_url) ? 'checked' : ''} style="width: 20px; height: 20px; cursor: pointer;">
      </div>`;

    const spotifyBtn = track.spotify_url
      ? `<a href="${escHtml(track.spotify_url)}" target="_blank" class="link-btn spotify">🎵 Spotify</a>`
      : '';

    const ytMusicBtn = track.youtube_music_url
      ? `<a href="${escHtml(track.youtube_music_url)}" target="_blank" class="link-btn ytmusic">🎶 YT Music</a>`
      : '';

    const ytBtn = track.youtube_url
      ? `<a href="${escHtml(track.youtube_url)}" target="_blank" class="link-btn youtube">▶ YouTube</a>`
      : '';

    const downloadBtn = (track.youtube_music_url || track.youtube_url)
      ? `<button class="btn-outline btn-dl-track" onclick="downloadTrack('${escHtml(track.youtube_music_url || track.youtube_url)}', '${escHtml(track.name.replace(/'/g, "\\'" ))}', '${escHtml(track.artist_string.replace(/'/g, "\\'" ))}', this)">&#8659; Save to Server</button>`
      : '';

    const streamBtn = (track.youtube_music_url || track.youtube_url)
      ? `<button class="btn-stream btn-dl-track" onclick="streamTrack('${escHtml(track.youtube_music_url || track.youtube_url)}', '${escHtml(track.name.replace(/'/g, "\\'" ))}', '${escHtml(track.artist_string.replace(/'/g, "\\'" ))}', this)">📥 Direct Download</button>`
      : '';

    const ytMatch = track.yt_title
      ? `<div class="yt-match">🔍 Matched: ${escHtml(track.yt_title)}</div>`
      : '';

    card.innerHTML = `
      <div class="track-top">
        ${checkboxHtml}
        ${artHtml}
        <div class="track-info">
          <div class="track-name" title="${escHtml(track.name)}">${escHtml(track.name)}</div>
          <div class="track-artist">${escHtml(track.artist_string)}</div>
          <div class="track-duration">⏱ ${track.duration_str}</div>
        </div>
        <span class="track-status-badge ${track.status}">${track.status === 'found' ? '✅ Found' : '❌ Not found'}</span>
      </div>
      <div class="track-links">
        ${spotifyBtn}
        ${ytMusicBtn}
        ${ytBtn}
        ${downloadBtn}
        ${streamBtn}
      </div>
      ${ytMatch}
    `;
    grid.appendChild(card);
  });
}

// ==============================
// FILTER & SELECTION
// ==============================
function toggleSelectMode() {
  selectMode = !selectMode;
  const btn = document.getElementById('toggleSelectBtn');
  btn.classList.toggle('active', selectMode);
  btn.textContent = selectMode ? 'Done Selecting' : '✓ Select';
  
  if (!selectMode) {
    selectedTracks.clear();
  }
  
  updateSelectUI();
  renderTracks(allTracks); // re-render to show/hide checkboxes
}

function toggleTrackSelect(checkbox, ytUrl) {
  if (checkbox.checked) {
    selectedTracks.add(ytUrl);
  } else {
    selectedTracks.delete(ytUrl);
  }
  updateSelectUI();
}

function updateSelectUI() {
  const btn = document.getElementById('downloadSelectedBtn');
  if (selectMode && selectedTracks.size > 0) {
    btn.style.display = 'inline-block';
    btn.textContent = `⬇ Download Selected (${selectedTracks.size})`;
  } else {
    btn.style.display = 'none';
  }
}

function setFilter(filter, btn) {
  activeFilter = filter;
  document.querySelectorAll('.filter-tag').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  applyFilters();
}

function filterTracks() {
  applyFilters();
}

function applyFilters() {
  const query = document.getElementById('searchFilter').value.toLowerCase();
  let filtered = allTracks;

  if (activeFilter === 'found') filtered = filtered.filter(t => t.status === 'found');
  if (activeFilter === 'not_found') filtered = filtered.filter(t => t.status === 'not_found');

  if (query) {
    filtered = filtered.filter(t =>
      t.name.toLowerCase().includes(query) ||
      t.artist_string.toLowerCase().includes(query)
    );
  }
  renderTracks(filtered);
}

// ==============================
// HISTORY / PLAYLISTS
// ==============================
async function loadPlaylist(playlistId) {
  showView('home');
  currentPlaylistId = playlistId;
  document.getElementById('progressCard').style.display = 'none';

  const res = await fetch(`/api/playlists/${playlistId}`);
  const data = await res.json();
  const playlist = data.playlist;
  const tracks = data.tracks;

  // Map DB format to display format
  allTracks = tracks.map(t => ({
    name: t.track_name,
    artist_string: t.artists.join(', '),
    album_art: t.album_art,
    duration_str: t.duration_str,
    spotify_url: t.spotify_url,
    youtube_music_url: t.youtube_music_url,
    youtube_url: t.youtube_url,
    yt_title: t.yt_title,
    yt_thumbnail: t.yt_thumbnail,
    status: t.status,
  }));

  const found = allTracks.filter(t => t.status === 'found').length;
  document.getElementById('resultsTitle').textContent = playlist.playlist_name;
  document.getElementById('resultsSubtitle').textContent =
    `${allTracks.length} tracks · ${found} found on YouTube Music`;

  document.getElementById('resultsSection').style.display = 'block';
  renderTracks(allTracks);
  document.getElementById('resultsSection').scrollIntoView({ behavior: 'smooth' });
}

async function deletePlaylist(playlistId, btn) {
  if (!confirm('Delete this playlist?')) return;
  await fetch(`/api/playlists/${playlistId}/delete`, { method: 'DELETE' });
  btn.closest('.playlist-card').remove();
  showToast('Playlist deleted', 'info');
}

// ==============================
// DOWNLOADS
// ==============================
async function downloadTrack(url, title, artist, btn) {
  const quality = document.getElementById('qualitySelect').value;
  btn.disabled = true;
  const originalText = btn.innerHTML;
  btn.innerHTML = '⏳...';
  
  const params = new URLSearchParams({ url, title, artist, quality });
  const downloadUrl = `/api/download/track?${params}`;
  
  // Use a hidden <a> click so we don't navigate away from the page
  const a = document.createElement('a');
  a.href = downloadUrl;
  a.download = title || 'track';
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  setTimeout(() => document.body.removeChild(a), 1000);
  
  setTimeout(() => { btn.innerHTML = '✅ Done'; }, 2000);
  setTimeout(() => { btn.innerHTML = originalText; btn.disabled = false; }, 4000);
}

async function streamTrack(url, title, artist, btn) {
  /**
   * Direct-to-browser download:
   * The server fetches the song via yt-dlp, pipes it straight to the
   * browser, and deletes the temp file. The user gets the file directly.
   */
  const quality = document.getElementById('qualitySelect').value;
  btn.disabled = true;
  const originalText = btn.innerHTML;
  btn.innerHTML = '⏳ Fetching...';
  btn.style.opacity = '0.7';

  showToast('⏳ Fetching song from YouTube... this may take 5–20s', 'info');

  const params = new URLSearchParams({ url, title, artist, quality });
  const streamUrl = `/api/stream/track?${params}`;

  try {
    // Fetch the response as a blob — this keeps the user on the page
    const res = await fetch(streamUrl);

    if (!res.ok) {
      let errMsg = 'Download failed';
      try { const d = await res.json(); errMsg = d.error || errMsg; } catch(_) {}
      throw new Error(errMsg);
    }

    // Read the audio blob
    const blob = await res.blob();
    const contentDisp = res.headers.get('Content-Disposition') || '';
    let filename = `${title} - ${artist}.m4a`;
    const match = contentDisp.match(/filename="?([^"]+)"?/);
    if (match) filename = match[1];

    // Trigger native browser save dialog
    const objUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = objUrl;
    a.download = filename;
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { document.body.removeChild(a); URL.revokeObjectURL(objUrl); }, 2000);

    btn.innerHTML = '✅ Downloaded!';
    btn.style.opacity = '1';
    showToast(`✅ '${title}' downloaded to your device!`, 'success');
    setTimeout(() => { btn.innerHTML = originalText; btn.disabled = false; }, 3000);

  } catch (err) {
    btn.innerHTML = '❌ Failed';
    btn.style.opacity = '1';
    btn.style.borderColor = '#ff6b6b';
    showToast(`❌ ${err.message}`, 'error');
    setTimeout(() => { btn.innerHTML = originalText; btn.disabled = false; btn.style.borderColor = ''; }, 3000);
  }
}

let dlPollInterval = null;

async function downloadAll() {
  if (!currentPlaylistId) return;
  startBatchDownload(currentPlaylistId, null);
}

async function downloadSelected() {
  if (!currentPlaylistId || selectedTracks.size === 0) return;
  startBatchDownload(currentPlaylistId, Array.from(selectedTracks));
}

async function startBatchDownload(playlistId, selectedUrls) {
  const quality = document.getElementById('qualitySelect').value;
  const btn = selectedUrls ? document.getElementById('downloadSelectedBtn') : document.getElementById('downloadAllBtn');
  btn.disabled = true;
  
  try {
    const payload = { quality };
    if (selectedUrls) payload.selected_urls = selectedUrls;

    const res = await fetch(`/api/download/playlist/${playlistId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    
    const jobId = data.job_id;
    document.getElementById('dlModal').style.display = 'flex';
    document.getElementById('dlProgressFill').style.width = '0%';
    document.getElementById('dlModalStats').textContent = `0 / ${data.total} tracks`;
    document.getElementById('dlModalEta').textContent = 'ETA: calculating...';
    document.getElementById('dlModalFolder').textContent = 'Starting download...';
    
    if (dlPollInterval) clearInterval(dlPollInterval);
    dlPollInterval = setInterval(() => pollDownloadJob(jobId, btn), 1000);
  } catch (err) {
    showToast(`Error: ${err.message}`, 'error');
    btn.disabled = false;
  }
}

function formatEta(seconds) {
  if (seconds == null || isNaN(seconds)) return 'calculating...';
  if (seconds === 0) return 'done';
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

async function pollDownloadJob(jobId, btn) {
  try {
    const res = await fetch(`/api/download/status/${jobId}`);
    
    // 404 = server restarted and lost the job from memory
    if (res.status === 404) {
      clearInterval(dlPollInterval);
      if (btn) btn.disabled = false;
      showToast('⚠️ Server restarted during download. Please try again.', 'error');
      closeDlModal();
      return;
    }

    const job = await res.json();
    
    if (job.total > 0) {
      document.getElementById('dlModalStats').textContent = `${job.progress} / ${job.total} tracks`;
      document.getElementById('dlProgressFill').style.width = `${(job.progress / job.total) * 100}%`;
    }

    document.getElementById('dlModalEta').textContent = `ETA: ${formatEta(job.eta_seconds)}`;

    if (job.folder) {
      document.getElementById('dlModalFolder').textContent = `⬇️ Downloading to server...`;
    }
    
    if (job.status === 'done' || job.status === 'error') {
      clearInterval(dlPollInterval);
      if (btn) btn.disabled = false;

      if (job.status === 'done') {
        document.getElementById('dlModalStats').textContent = `${job.total} / ${job.total} tracks — Done!`;
        document.getElementById('dlModalEta').textContent = 'Finished!';
        document.getElementById('dlModal').querySelector('.dl-modal-title').textContent = '✅ Ready to Download!';
        
        const folderEl = document.getElementById('dlModalFolder');
        
        if (job.zip_path) {
          // ZIP is ready — show download button
          folderEl.innerHTML = `<a href="/api/download/zip/${jobId}" class="btn-primary" style="display:inline-block; padding:12px 28px; text-decoration:none; margin-top:15px; font-size:1rem; font-weight:700; border-radius:10px;">📥 Save ZIP to Device</a>`;
          showToast('✅ Ready! Tap the button to save your playlist.', 'success');
        } else if (job.zip_error) {
          // Songs downloaded but zipping failed (e.g. disk full)
          folderEl.textContent = `⚠️ Songs downloaded but ZIP failed: ${job.zip_error}`;
          showToast(`⚠️ ${job.zip_error}`, 'error');
        } else {
          // Zipping still in progress (rare race condition)
          folderEl.textContent = '⏳ Preparing ZIP... please wait.';
          // Keep polling
          dlPollInterval = setInterval(() => pollDownloadJob(jobId, btn), 2000);
          return;
        }
        
        if (selectMode) toggleSelectMode();
      } else {
        showToast(`❌ Download error: ${job.error || 'Unknown error'}`, 'error');
      }
    }
  } catch (e) {
    console.error('Poll error:', e);
  }
}


function closeDlModal() {
  document.getElementById('dlModal').style.display = 'none';
}

// ==============================
// EXPORT
// ==============================
function exportCSV() {
  if (!currentPlaylistId) return;
  window.open(`/api/playlists/${currentPlaylistId}/export/csv`, '_blank');
}

function exportJSON() {
  if (!currentPlaylistId) return;
  window.open(`/api/playlists/${currentPlaylistId}/export/json`, '_blank');
}

function exportCSVById(id) {
  window.open(`/api/playlists/${id}/export/csv`, '_blank');
}

// ==============================
// TOAST
// ==============================
function showToast(message, type = 'info') {
  let container = document.querySelector('.toast-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}

// ==============================
// UTILS
// ==============================
function escHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// Allow pressing Enter to convert
document.addEventListener('DOMContentLoaded', () => {
  const urlInput = document.getElementById('playlistUrl');
  if (urlInput) {
    urlInput.addEventListener('keydown', e => {
      if (e.key === 'Enter') startConversion();
    });
  }
  // Check cookie status on load
  checkCookieStatus();
});

// ==============================
// SETTINGS — COOKIES
// ==============================
async function checkCookieStatus() {
  try {
    const res = await fetch('/api/cookies/status');
    const data = await res.json();
    const badge = document.getElementById('cookieStatusBadge');
    const deleteBtn = document.getElementById('deleteCookieBtn');
    if (data.has_cookies) {
      badge.textContent = '✅ Cookies Active';
      badge.style.background = 'rgba(29,185,84,0.15)';
      badge.style.color = '#1db954';
      badge.style.border = '1px solid #1db954';
      if (deleteBtn) deleteBtn.style.display = 'inline-block';
    } else {
      badge.textContent = '⚠️ No Cookies';
      badge.style.background = 'rgba(255,107,107,0.15)';
      badge.style.color = '#ff6b6b';
      badge.style.border = '1px solid #ff6b6b';
      if (deleteBtn) deleteBtn.style.display = 'none';
    }
  } catch (e) {
    console.error('Cookie status check failed:', e);
  }
}

async function uploadCookies(input) {
  const file = input.files[0];
  if (!file) return;
  const statusEl = document.getElementById('cookieUploadStatus');
  statusEl.textContent = '⏳ Uploading...';
  statusEl.style.color = '#aaa';

  const formData = new FormData();
  formData.append('cookies', file);

  try {
    const res = await fetch('/api/cookies/upload', { method: 'POST', body: formData });
    const data = await res.json();
    if (data.ok) {
      statusEl.textContent = '✅ ' + data.message;
      statusEl.style.color = '#1db954';
      showToast('✅ YouTube cookies saved! Downloads will now work.', 'success');
      checkCookieStatus();
    } else {
      statusEl.textContent = '❌ ' + (data.error || 'Upload failed');
      statusEl.style.color = '#ff6b6b';
      showToast('❌ ' + (data.error || 'Upload failed'), 'error');
    }
  } catch (e) {
    statusEl.textContent = '❌ Network error during upload';
    statusEl.style.color = '#ff6b6b';
  }
  // Reset file input so same file can be re-uploaded
  input.value = '';
}

async function deleteCookies() {
  if (!confirm('Remove saved YouTube cookies?')) return;
  await fetch('/api/cookies/delete', { method: 'DELETE' });
  showToast('🗑 Cookies removed', 'info');
  checkCookieStatus();
  const statusEl = document.getElementById('cookieUploadStatus');
  if (statusEl) statusEl.textContent = '';
}
