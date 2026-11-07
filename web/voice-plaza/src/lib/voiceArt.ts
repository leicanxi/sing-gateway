/**
 * Deterministic colour art for a voice. The catalog has no cover images, so a
 * stable hue pair derived from the name gives every entry a recognisable face.
 */
function hashName(name: string): number {
  let hash = 0;
  for (let index = 0; index < name.length; index += 1) {
    hash = (hash * 31 + name.charCodeAt(index)) >>> 0;
  }
  return hash;
}

export function voiceArt(name: string): { avatar: string; tile: string } {
  const hash = hashName(name);
  const hue = hash % 360;
  const second = (hue + 35 + ((hash >>> 8) % 90)) % 360;

  return {
    avatar: `conic-gradient(from 180deg, hsl(${hue} 78% 58%) 0%, #fff 25%, hsl(${hue} 80% 96%) 30%, hsl(${hue} 78% 58%) 60%, hsl(${hue} 80% 96%) 80%, #fff 85%, hsl(${hue} 78% 58%) 100%)`,
    tile: `linear-gradient(155deg, hsl(${hue} 56% 52%) 0%, hsl(${second} 50% 34%) 100%)`,
  };
}
