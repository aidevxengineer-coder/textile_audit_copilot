import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const ACCESS_COOKIE = "auditready_access";
const REFRESH_COOKIE = "auditready_refresh";

export function proxy(request: NextRequest) {
  const hasAccessToken = Boolean(request.cookies.get(ACCESS_COOKIE)?.value);
  const hasRefreshToken = Boolean(request.cookies.get(REFRESH_COOKIE)?.value);
  const hasSession = hasAccessToken || hasRefreshToken;
  const pathname = request.nextUrl.pathname;

  const protectedRoute =
    pathname.startsWith("/chat") ||
    pathname.startsWith("/report") ||
    pathname.startsWith("/admin");
  const authRoute = pathname === "/login" || pathname === "/mfa";

  if (protectedRoute && !hasSession) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  if (authRoute && hasSession) {
    return NextResponse.redirect(new URL("/chat", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/chat/:path*", "/report/:path*", "/admin/:path*", "/login", "/mfa"],
};
