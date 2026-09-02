export function BrandMark({ small = false }: { small?: boolean }) {
  const size = small ? 48 : 68;
  return (
    <svg
      aria-hidden="true"
      className="brand-mark"
      viewBox="0 0 64 64"
      width={size}
      height={size}
      fill="none"
    >
      <defs>
        <linearGradient id="auditready-brand" x1="8" x2="56" y1="8" y2="56">
          <stop stopColor="#D83E2C" />
          <stop offset="0.55" stopColor="#A91E22" />
          <stop offset="1" stopColor="#046A38" />
        </linearGradient>
      </defs>
      <path
        d="M32 6 54 14v14c0 16.8-8.4 25.8-22 30C18.4 53.8 10 44.8 10 28V14L32 6Z"
        fill="url(#auditready-brand)"
      />
      <path
        d="M32 18c-5.8 0-10.5 4.8-10.5 10.7 0 5.3 3.8 9.8 8.9 10.6v8.4h3.2v-8.4c5.1-.8 8.9-5.3 8.9-10.6C42.5 22.8 37.8 18 32 18Z"
        fill="#F3BE4E"
      />
      <path d="M32 22.2 28.9 29h6.2L32 22.2Z" fill="#0B1D17" />
      <circle cx="32" cy="30.4" r="2.5" fill="#0B1D17" />
    </svg>
  );
}
