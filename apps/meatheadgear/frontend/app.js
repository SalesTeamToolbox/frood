/**
 * MeatheadGear SPA — Client-side application logic
 *
 * Functions:
 *  1. init()              — Bootstrap on DOMContentLoaded
 *  2. checkAuth()         — Verify stored JWT and update nav
 *  3. fetchProducts()     — Load product list from catalog API
 *  4. renderProductGrid() — Render product cards in the grid
 *  5. showProductDetail() — Load and render a single product
 *  6. showAuthModal()     — Open the auth modal
 *  7. hideAuthModal()     — Close the auth modal
 *  8. toggleAuthMode()    — Switch between login / register
 *  9. handleAuth()        — Submit register or login form
 * 10. signOut()           — Clear session and update nav
 * 11. showProducts()      — Show the product grid view
 * 12. showSizeGuide()     — Open the size guide modal
 * 13. hideSizeGuide()     — Close the size guide modal
 * 14. filterProducts()    — Filter grid by category
 */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const state = {
  token: localStorage.getItem('mg_token') || null,
  user: null,
  products: [],
  currentProduct: null,
  authMode: 'login', // 'login' | 'register'
};

// ---------------------------------------------------------------------------
// 1. init — Bootstrap
// ---------------------------------------------------------------------------

async function init() {
  if (state.token) {
    await checkAuth();
  }
  await fetchProducts();
}

document.addEventListener('DOMContentLoaded', init);

// ---------------------------------------------------------------------------
// 2. checkAuth — Verify stored JWT with /api/auth/me
// ---------------------------------------------------------------------------

async function checkAuth() {
  try {
    const res = await fetch('/api/auth/me', {
      headers: { 'Authorization': 'Bearer ' + state.token },
    });

    if (res.ok) {
      const user = await res.json();
      state.user = user;
      updateNavAuth(user);
    } else {
      // Token invalid or expired — clear it
      localStorage.removeItem('mg_token');
      state.token = null;
      state.user = null;
    }
  } catch (err) {
    // Network error — keep token but don't crash
    console.warn('Auth check failed:', err);
  }
}

function updateNavAuth(user) {
  const navAuth = document.getElementById('nav-auth');
  const navUser = document.getElementById('nav-user');
  const navOrders = document.getElementById('nav-orders');
  const navUserEmail = document.getElementById('nav-user-email');

  if (user) {
    navAuth.classList.add('hidden');
    navUser.classList.remove('hidden');
    navOrders.classList.remove('hidden');
    navUserEmail.textContent = user.email;
  } else {
    navAuth.classList.remove('hidden');
    navUser.classList.add('hidden');
    navOrders.classList.add('hidden');
  }
}

// ---------------------------------------------------------------------------
// 3. fetchProducts — Load product list from catalog API
// ---------------------------------------------------------------------------

async function fetchProducts(category = null) {
  const loading = document.getElementById('products-loading');
  const empty = document.getElementById('products-empty');
  const container = document.getElementById('products-container');

  loading.classList.remove('hidden');
  empty.classList.add('hidden');
  container.classList.add('hidden');

  try {
    const url = '/api/catalog/products' + (category ? '?category=' + encodeURIComponent(category) : '');
    const res = await fetch(url);

    if (!res.ok) {
      throw new Error('Failed to load products: ' + res.status);
    }

    const data = await res.json();
    state.products = data.products || [];
    renderProductGrid();
  } catch (err) {
    console.error('fetchProducts error:', err);
    loading.classList.add('hidden');
    empty.classList.remove('hidden');
  }
}

// ---------------------------------------------------------------------------
// 4. renderProductGrid — Render product cards
// ---------------------------------------------------------------------------

function renderProductGrid() {
  const loading = document.getElementById('products-loading');
  const empty = document.getElementById('products-empty');
  const container = document.getElementById('products-container');

  loading.classList.add('hidden');

  if (!state.products || state.products.length === 0) {
    empty.classList.remove('hidden');
    container.classList.add('hidden');
    return;
  }

  empty.classList.add('hidden');
  container.classList.remove('hidden');

  container.innerHTML = '';
  state.products.forEach(product => {
    const card = createProductCard(product);
    container.appendChild(card);
  });
}

function createProductCard(product) {
  const card = document.createElement('div');
  card.className = 'product-card';
  card.setAttribute('role', 'button');
  card.setAttribute('tabindex', '0');
  card.onclick = () => showProductDetail(product.id);
  card.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') showProductDetail(product.id); };

  // Format price
  const priceMin = parseFloat(product.price_min) || 0;
  const priceMax = parseFloat(product.price_max) || 0;
  let priceText;
  if (priceMin === 0 && priceMax === 0) {
    priceText = 'Price TBD';
  } else if (priceMin === priceMax || priceMax === 0) {
    priceText = '$' + priceMin.toFixed(2);
  } else {
    priceText = '$' + priceMin.toFixed(2) + ' &ndash; $' + priceMax.toFixed(2);
  }

  // Image or placeholder
  let imageHtml;
  if (product.thumbnail_url) {
    imageHtml = `<img
      class="product-card-image"
      src="${escapeAttr(product.thumbnail_url)}"
      alt="${escapeAttr(product.name)}"
      loading="lazy"
      onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';"
    />
    <div class="product-card-image-placeholder" style="display:none;">&#128683;</div>`;
  } else {
    imageHtml = `<div class="product-card-image-placeholder">&#128683;</div>`;
  }

  card.innerHTML = `
    ${imageHtml}
    <div class="product-card-body">
      <div class="product-card-name">${escapeHtml(product.name)}</div>
      <div class="product-card-price">${priceText}</div>
      <button class="btn-primary product-card-cta" onclick="event.stopPropagation(); showProductDetail(${product.id})">
        DESIGN IT
      </button>
    </div>
  `;

  return card;
}

// ---------------------------------------------------------------------------
// 5. showProductDetail — Fetch and render a single product
// ---------------------------------------------------------------------------

async function showProductDetail(productId) {
  // Switch view
  document.getElementById('hero').classList.add('hidden');
  document.getElementById('product-grid').classList.add('hidden');
  document.getElementById('product-detail').classList.remove('hidden');

  const content = document.getElementById('product-detail-content');
  content.innerHTML = '<div class="loading-state"><div class="spinner"></div><p>Loading product&hellip;</p></div>';

  window.scrollTo({ top: 0, behavior: 'smooth' });

  try {
    const res = await fetch('/api/catalog/products/' + productId);
    if (!res.ok) throw new Error('Product not found: ' + res.status);

    const product = await res.json();
    state.currentProduct = product;
    renderProductDetail(product);
  } catch (err) {
    content.innerHTML = `
      <div class="empty-state">
        <h3>Product Not Found</h3>
        <p class="empty-sub">Sorry, we couldn&rsquo;t load that product.</p>
        <button class="btn-secondary" onclick="showProducts()" style="margin-top:20px;">Back to Shop</button>
      </div>
    `;
  }
}

function renderProductDetail(product) {
  const content = document.getElementById('product-detail-content');

  // Build image gallery
  const images = product.images || [];
  const thumbnail = product.thumbnail_url;

  // Collect unique image URLs
  const allImages = [];
  if (thumbnail) allImages.push(thumbnail);
  images.forEach(img => { if (img.url && !allImages.includes(img.url)) allImages.push(img.url); });

  let mainImageHtml;
  if (allImages.length > 0) {
    mainImageHtml = `<img id="detail-main-img" class="detail-main-image" src="${escapeAttr(allImages[0])}" alt="${escapeAttr(product.name)}" />`;
  } else {
    mainImageHtml = `<div class="detail-main-placeholder">&#128683;</div>`;
  }

  let thumbnailsHtml = '';
  if (allImages.length > 1) {
    thumbnailsHtml = '<div class="detail-thumbnails">';
    allImages.forEach((url, i) => {
      thumbnailsHtml += `<img
        class="detail-thumbnail ${i === 0 ? 'active' : ''}"
        src="${escapeAttr(url)}"
        alt="View ${i + 1}"
        onclick="swapMainImage(this, '${escapeAttr(url)}')"
        loading="lazy"
      />`;
    });
    thumbnailsHtml += '</div>';
  }

  // Build color swatches (deduplicated by color name)
  const variants = product.variants || [];
  const colorMap = new Map();
  variants.forEach(v => {
    if (v.color && !colorMap.has(v.color)) {
      colorMap.set(v.color, v.color_hex || '#888888');
    }
  });

  let swatchesHtml = '';
  if (colorMap.size > 0) {
    swatchesHtml = `
      <div class="detail-section-label">Color</div>
      <div class="color-swatches" id="color-swatches">
    `;
    let first = true;
    colorMap.forEach((hex, colorName) => {
      const safeName = escapeAttr(colorName);
      const safeHex = escapeAttr(hex);
      swatchesHtml += `<div
        class="color-swatch ${first ? 'active' : ''}"
        style="background-color:${safeHex};"
        title="${safeName}"
        onclick="selectColor(this, '${safeName}')"
      ></div>`;
      first = false;
    });
    swatchesHtml += '</div>';
  }

  // Build size buttons — unique sizes for currently selected color
  const firstColor = colorMap.size > 0 ? Array.from(colorMap.keys())[0] : null;
  const sizeVariants = variants.filter(v => !firstColor || v.color === firstColor);
  const sizeMap = new Map();
  sizeVariants.forEach(v => {
    if (v.size) sizeMap.set(v.size, v.in_stock);
  });

  let sizesHtml = '';
  if (sizeMap.size > 0) {
    sizesHtml = `
      <div class="detail-section-label">Size</div>
      <div class="size-buttons" id="size-buttons">
    `;
    sizeMap.forEach((inStock, sizeName) => {
      sizesHtml += `<button
        class="size-btn"
        ${!inStock ? 'disabled' : ''}
        onclick="selectSize(this)"
        data-size="${escapeAttr(sizeName)}"
      >${escapeHtml(sizeName)}</button>`;
    });
    sizesHtml += '</div>';
    sizesHtml += `<a class="size-guide-link" onclick="showSizeGuide(); return false;" href="#">Size Guide</a>`;
  }

  // Price display
  const priceDisplay = getPriceForColor(product, firstColor);

  // Description
  const descHtml = product.description
    ? `<div class="detail-description">${escapeHtml(product.description)}</div>`
    : '';

  content.innerHTML = `
    <div class="detail-back">
      <a href="#" onclick="showProducts(); return false;">&larr; Back to Shop</a>
    </div>
    <div class="detail-layout">
      <div class="detail-gallery">
        ${mainImageHtml}
        ${thumbnailsHtml}
      </div>
      <div class="detail-info">
        <div class="detail-category">${escapeHtml(product.category || '')}</div>
        <h1 class="detail-name">${escapeHtml(product.name)}</h1>
        <div class="detail-price" id="detail-price">${priceDisplay}</div>
        ${swatchesHtml}
        ${sizesHtml}
        ${descHtml}
        <button class="btn-primary detail-cta" onclick="handleDesignIt()">
          DESIGN IT
        </button>
      </div>
    </div>
  `;
}

function getPriceForColor(product, colorName) {
  const variants = product.variants || [];
  const matching = variants.filter(v => !colorName || v.color === colorName);
  if (matching.length === 0) return 'Price TBD';
  const prices = matching.map(v => parseFloat(v.retail_price)).filter(p => !isNaN(p));
  if (prices.length === 0) return 'Price TBD';
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  return min === max ? '$' + min.toFixed(2) : '$' + min.toFixed(2) + ' &ndash; $' + max.toFixed(2);
}

function swapMainImage(thumb, url) {
  const mainImg = document.getElementById('detail-main-img');
  if (mainImg) mainImg.src = url;
  document.querySelectorAll('.detail-thumbnail').forEach(t => t.classList.remove('active'));
  thumb.classList.add('active');
}

function selectColor(swatch, colorName) {
  document.querySelectorAll('.color-swatch').forEach(s => s.classList.remove('active'));
  swatch.classList.add('active');

  // Re-render size buttons for selected color
  if (state.currentProduct) {
    const variants = state.currentProduct.variants || [];
    const sizeVariants = variants.filter(v => v.color === colorName);
    const sizeMap = new Map();
    sizeVariants.forEach(v => {
      if (v.size) sizeMap.set(v.size, v.in_stock);
    });

    const sizeContainer = document.getElementById('size-buttons');
    if (sizeContainer) {
      sizeContainer.innerHTML = '';
      sizeMap.forEach((inStock, sizeName) => {
        const btn = document.createElement('button');
        btn.className = 'size-btn';
        btn.disabled = !inStock;
        btn.dataset.size = sizeName;
        btn.textContent = sizeName;
        btn.onclick = () => selectSize(btn);
        sizeContainer.appendChild(btn);
      });
    }

    // Update price
    const priceEl = document.getElementById('detail-price');
    if (priceEl) {
      priceEl.innerHTML = getPriceForColor(state.currentProduct, colorName);
    }
  }
}

function selectSize(btn) {
  document.querySelectorAll('.size-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
}

function handleDesignIt() {
  if (!state.user) {
    showAuthModal();
    return;
  }
  // Placeholder: future design studio integration
  alert('Design studio coming soon! Sign in to save your designs.');
}

// ---------------------------------------------------------------------------
// 6 & 7. showAuthModal / hideAuthModal
// ---------------------------------------------------------------------------

function showAuthModal() {
  const modal = document.getElementById('auth-modal');
  modal.classList.remove('hidden');
  // Reset form
  document.getElementById('auth-form').reset();
  document.getElementById('auth-error').classList.add('hidden');
  // Focus email input after small delay
  setTimeout(() => {
    const emailInput = document.getElementById('auth-email');
    if (emailInput) emailInput.focus();
  }, 50);
}

function hideAuthModal() {
  document.getElementById('auth-modal').classList.add('hidden');
}

function handleModalBackdropClick(event) {
  if (event.target === document.getElementById('auth-modal')) {
    hideAuthModal();
  }
}

// ---------------------------------------------------------------------------
// 8. toggleAuthMode — Switch between login and register
// ---------------------------------------------------------------------------

function toggleAuthMode() {
  const isLogin = state.authMode === 'login';
  state.authMode = isLogin ? 'register' : 'login';

  const title = document.getElementById('auth-title');
  const submit = document.getElementById('auth-submit');
  const nameField = document.getElementById('auth-name-field');
  const toggleText = document.getElementById('auth-toggle-text');
  const toggleLink = document.getElementById('auth-toggle-link');
  const passwordInput = document.getElementById('auth-password');

  if (state.authMode === 'register') {
    title.textContent = 'CREATE ACCOUNT';
    submit.textContent = 'CREATE ACCOUNT';
    nameField.classList.remove('hidden');
    toggleText.textContent = 'Already have an account?';
    toggleLink.textContent = 'Sign In';
    passwordInput.setAttribute('autocomplete', 'new-password');
  } else {
    title.textContent = 'SIGN IN';
    submit.textContent = 'SIGN IN';
    nameField.classList.add('hidden');
    toggleText.textContent = "Don't have an account?";
    toggleLink.textContent = 'Sign Up';
    passwordInput.setAttribute('autocomplete', 'current-password');
  }

  // Clear error
  const errorEl = document.getElementById('auth-error');
  errorEl.classList.add('hidden');
  errorEl.textContent = '';
}

// ---------------------------------------------------------------------------
// 9. handleAuth — Submit register or login
// ---------------------------------------------------------------------------

async function handleAuth(event) {
  event.preventDefault();

  const errorEl = document.getElementById('auth-error');
  const submitBtn = document.getElementById('auth-submit');
  const email = document.getElementById('auth-email').value.trim();
  const password = document.getElementById('auth-password').value;
  const name = document.getElementById('auth-name').value.trim();

  errorEl.classList.add('hidden');
  errorEl.textContent = '';
  submitBtn.disabled = true;

  try {
    if (state.authMode === 'register') {
      // Register first
      const regRes = await fetch('/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password, name }),
      });

      if (!regRes.ok) {
        const err = await regRes.json().catch(() => ({}));
        throw new Error(err.detail || 'Registration failed. Please try again.');
      }

      // Auto-login after register
      const loginRes = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });

      if (!loginRes.ok) {
        throw new Error('Account created. Please sign in manually.');
      }

      const loginData = await loginRes.json();
      await _onLoginSuccess(loginData.access_token);
    } else {
      // Login
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Invalid email or password.');
      }

      const data = await res.json();
      await _onLoginSuccess(data.access_token);
    }
  } catch (err) {
    errorEl.textContent = err.message || 'Something went wrong. Please try again.';
    errorEl.classList.remove('hidden');
  } finally {
    submitBtn.disabled = false;
  }
}

async function _onLoginSuccess(token) {
  localStorage.setItem('mg_token', token);
  state.token = token;
  await checkAuth();
  hideAuthModal();
}

// ---------------------------------------------------------------------------
// 10. signOut — Clear session
// ---------------------------------------------------------------------------

function signOut() {
  localStorage.removeItem('mg_token');
  state.token = null;
  state.user = null;
  updateNavAuth(null);
}

// ---------------------------------------------------------------------------
// 11. showProducts — Show the product grid view
// ---------------------------------------------------------------------------

function showProducts() {
  document.getElementById('hero').classList.add('hidden');
  document.getElementById('product-detail').classList.add('hidden');
  document.getElementById('product-grid').classList.remove('hidden');
  window.scrollTo({ top: 0, behavior: 'smooth' });

  // Re-render if we have products loaded
  if (state.products.length === 0) {
    fetchProducts();
  } else {
    renderProductGrid();
  }
}

// ---------------------------------------------------------------------------
// 12 & 13. showSizeGuide / hideSizeGuide
// ---------------------------------------------------------------------------

function showSizeGuide() {
  document.getElementById('size-modal').classList.remove('hidden');
}

function hideSizeGuide() {
  document.getElementById('size-modal').classList.add('hidden');
}

function handleSizeModalBackdropClick(event) {
  if (event.target === document.getElementById('size-modal')) {
    hideSizeGuide();
  }
}

// ---------------------------------------------------------------------------
// 14. filterProducts — Filter product grid by category
// ---------------------------------------------------------------------------

async function filterProducts(category, btnEl) {
  // Update active filter button
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  if (btnEl) btnEl.classList.add('active');

  await fetchProducts(category);
}

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------

function escapeHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function escapeAttr(str) {
  if (str == null) return '';
  return String(str)
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
