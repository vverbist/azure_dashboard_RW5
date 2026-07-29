# Enabling sign-in (Microsoft Entra ID / Easy Auth)

This locks the dashboard so only your organisation's Microsoft accounts can reach it
(roadmap 2.3). The gate itself is an **Azure Portal** configuration on the App Service —
no code deploy is required for it. The app already reads the signed-in user and shows
"Signed in as … / Sign out" once the gate injects the identity.

## What you get

- Anyone opening the dashboard URL is redirected to Microsoft sign-in first.
- Only accounts in your tenant (e.g. `@hy-gro.nl`) can sign in (single-tenant).
- All routes, including the CSV download endpoints, are protected — the gate sits in
  front of the whole app.

## Prerequisites

- Access to the `turbine-rw5` App Service in the Azure Portal with permission to change
  Authentication settings.
- Permission to register an application in your Entra tenant (or an admin who can consent).

## Steps (Azure Portal)

1. Go to **App Services → `turbine-rw5` → Settings → Authentication**.
2. Click **Add identity provider**.
3. **Identity provider:** Microsoft.
4. **App registration type:** *Create new app registration*.
   - **Name:** e.g. `turbine-rw5-auth`.
   - **Supported account types:** **Current tenant – Single tenant** ← this is what limits
     access to your organisation only.
5. **Restrict access:** **Require authentication**.
6. **Unauthenticated requests:** **HTTP 302 Found redirect (recommended for websites)** –
   this sends visitors to the Microsoft login page.
7. Leave **Token store** enabled (default).
8. **Add / Save.**

That's the whole gate. Give it a minute, then test.

## Verify

1. Open the dashboard in a private/incognito window.
2. You should be redirected to Microsoft sign-in. Sign in with an org account.
3. The dashboard loads and the header shows **Signed in as \<you\> · Sign out**.
4. **Sign out** (the header link) goes to `/.auth/logout` and returns you to the login.

## Later: restrict to specific people or a group

Single-tenant already limits to your whole organisation. To narrow further:

1. **Microsoft Entra ID → Enterprise applications → `turbine-rw5-auth` → Properties**:
   set **Assignment required** = **Yes**.
2. **Users and groups → Add user/group**: assign only the people or the security group
   that should have access.

No code change is needed for either scope.

## Application-level defense in depth (`REQUIRE_AUTH`)

The platform gate is the real control. The app also rejects any `/api` request without an
Easy Auth identity when it detects that it is running on Azure App Service
(`WEBSITE_SITE_NAME` is present). This includes dataset listing and every CSV download.

- Local development remains open because `WEBSITE_SITE_NAME` is absent.
- `REQUIRE_AUTH=true` can force the check in another hosted environment.
- `REQUIRE_AUTH=false` can explicitly override it, but should not be used in production.

## Security note

The identity headers (`X-MS-CLIENT-PRINCIPAL-*`) are trustworthy **only** behind Easy Auth:
the platform authenticates the request and overwrites any client-supplied copies. Do not
rely on them (or enable `REQUIRE_AUTH`) unless the App Service Authentication gate is on.
