export async function copyText(text: string): Promise<boolean> {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Fall through to the legacy path (older Safari, non-secure origins).
    }
  }

  const helper = document.createElement('textarea');
  helper.value = text;
  helper.setAttribute('readonly', '');
  helper.style.position = 'fixed';
  helper.style.top = '-9999px';
  helper.style.opacity = '0';
  document.body.appendChild(helper);
  try {
    helper.select();
    helper.setSelectionRange(0, helper.value.length);
    return document.execCommand('copy');
  } catch {
    return false;
  } finally {
    helper.remove();
  }
}
