import { type NextRequest, NextResponse } from "next/server";

const SESSION_COOKIE = "mm_session";
const APP_PATHS = ["/chat", "/transactions", "/settings"];
const AUTH_PATHS = ["/login", "/register"];

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
  if (hasSession && AUTH_PATHS.includes(pathname)) {
    return NextResponse.redirect(new URL("/chat", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/chat/:path*", "/transactions/:path*", "/settings/:path*", "/login", "/register"],
};
