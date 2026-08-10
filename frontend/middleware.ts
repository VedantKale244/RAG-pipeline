import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Route protection middleware.
 *
 * - New / guest users land on "/" (landing page).
 * - Returning recognized users (graphrag_auth cookie) are auto-redirected from "/" to "/dashboard".
 * - /dashboard is public for guest trial; /login is public for auth.
 */

const PUBLIC_PATHS = ["/", "/login", "/_next", "/favicon.ico", "/coastal-bg.jpg"];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  const isPublic = pathname === "/" || PUBLIC_PATHS.some((p) => pathname.startsWith(p));
  if (isPublic) {
    const authCookie = request.cookies.get("graphrag_auth");

    // Returning recognized user on landing → go straight to dashboard
    if (pathname === "/" && authCookie?.value) {
      return NextResponse.redirect(new URL("/dashboard", request.url));
    }

    return NextResponse.next();
  }

  // Check auth cookie for protected routes
  const authCookie = request.cookies.get("graphrag_auth");
  if (!authCookie?.value) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("redirect", pathname);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
