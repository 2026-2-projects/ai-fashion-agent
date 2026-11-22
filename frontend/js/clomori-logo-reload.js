/** CLOMORI: clicking a header logo reloads the current page, preserving its hash route.
 * Existing app handlers can prevent navigation while a save/request is in progress.
 * This module does not read or write user data and does not call any API.
 */
document.addEventListener("click", (event) => {
  if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  const logo = event.target?.closest?.(".site-header a.logo");
  if (!logo) return;
  event.preventDefault();
  window.location.reload();
});
