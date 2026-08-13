export function SealMark({ size = 40 }: { size?: number }) {
  return (
    <svg
      viewBox="0 0 96 96"
      width={size}
      height={size}
      role="img"
      aria-label="言蹊"
      className="brand-mark"
    >
      <title>言蹊</title>
      <rect x="8" y="8" width="80" height="80" rx="13" fill="#14302C" />
      <rect x="13" y="13" width="70" height="70" rx="9" fill="none" stroke="#C9A45C" strokeWidth="1" />
      <text
        x="48"
        y="60"
        textAnchor="middle"
        fontFamily="'YanxiLogo','YanxiKai',serif"
        fontSize="34"
        fill="#F8F5EF"
        letterSpacing="2"
      >
        言蹊
      </text>
      <rect x="74" y="74" width="14" height="14" rx="3" fill="#C9A45C" />
    </svg>
  )
}
