import { type NextRequest, NextResponse } from "next/server";

const SESSION_COOKIE = "mm_session";
const APP_PATHS = ["/chat", "/transactions", "/accounts", "/reports", "/settings"];

/**
 * Optimistic routing only: avoids flashing the app shell for signed-out visitors. The API
 * remains the authority; an expired cookie still gets a 401 there and a redirect here.
 */
export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const hasSession = request.cookies.has(SESSION_COOKIE);
  if (!hasSession && APP_PATHS.some((path) => pathname.startsWith(path))) {
    const url = new URL("/login", request.url);
    url.searchParams.set("next", `${pathname}${search}`);
    return NextResponse.redirect(url);
  }
  // A cookie can be expired or revoked. Let login render; only the API can prove a session.
  return NextResponse.next();
}

export const config = {
  matcher: ["/chat/:path*", "/transactions/:path*", "/accounts/:path*", "/reports/:path*", "/settings/:path*"],
};
