import { getElement } from "../dom.js";
import { escapeHtml } from "../formatters.js";

// Azure Easy Auth logout; returns to the site root after signing out.
const LOGOUT_URL = "/.auth/logout?post_logout_redirect_uri=/";

export function renderUserBadge(me) {
  const badge = getElement("user-badge");
  const user = me?.user;

  // Unauthenticated (e.g. local dev without the platform gate): show nothing.
  if (!me?.authenticated || !user) {
    badge.hidden = true;
    badge.innerHTML = "";
    return;
  }

  const label = user.name || user.email || "Signed in";
  badge.hidden = false;
  badge.innerHTML = `
    <span class="user-name" title="${escapeHtml(user.email || "")}">${escapeHtml(label)}</span>
    <a class="user-signout" href="${LOGOUT_URL}">Sign out</a>
  `;
}
