/** Small vector PIP mark (spherical body, mast + ball tip, black visor, pill eyes). */
export function PipMark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" role="img" aria-label="PIP">
      <line x1="15" y1="10" x2="11" y2="3" stroke="#18181B" strokeWidth="2" strokeLinecap="round" />
      <circle cx="11" cy="3.5" r="2.6" fill="#E87A1E" stroke="#18181B" strokeWidth="1.4" />
      <ellipse cx="20" cy="23" rx="15" ry="13" fill="#FAF8F4" stroke="#18181B" strokeWidth="2.4" />
      <rect x="9.5" y="16.5" width="21" height="12" rx="4.5" fill="#18181B" />
      <rect x="14" y="19" width="3.2" height="7" rx="1.6" fill="#FAF8F4" />
      <rect x="22.8" y="19" width="3.2" height="7" rx="1.6" fill="#FAF8F4" />
    </svg>
  );
}
