import { useState, type FormEvent, type ReactNode } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { apiErrorMessage } from '../api/error'
import { useAuthStatus, useChangePassword, useLogin, useLogout, useSetup } from '../api/queries/auth'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { Notice } from '../ui/Notice'
import { OwlCoin } from '../ui/OwlCoin'
import { Spinner } from '../ui/Spinner'
import { cn } from '../ui/cn'
import { inputClass } from '../ui/inputClass'

const MIN_PASSWORD = 8

/** The owl, a title and one card: the frame every page outside the app shell shares. */
function AuthFrame({ title, description, children }: { title: string; description?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-bg px-4 py-10 text-fg">
      <div className="grid w-full max-w-[380px] gap-6">
        <div className="grid justify-items-center gap-3 text-center">
          <OwlCoin size={44} />
          <div className="grid gap-1">
            <h1 className="text-[20px] font-semibold tracking-[-0.01em]">{title}</h1>
            {description && <p className="text-[13px] text-fg-2">{description}</p>}
          </div>
        </div>
        <Card className="p-5">{children}</Card>
      </div>
    </div>
  )
}

function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="grid gap-1.5">
      <span className="text-[12.5px] text-fg-2">{label}</span>
      {children}
      {hint && <span className="text-[11.5px] text-fg-3">{hint}</span>}
    </label>
  )
}

const fieldClass = cn(inputClass, 'h-9 w-full')

/** Sign in. There is no sign-up: the admin creates accounts in Settings → Users. */
export function LoginPage() {
  const { data: status, isLoading } = useAuthStatus()
  const login = useLogin()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  if (isLoading) return <Centered><Spinner label="Loading…" /></Centered>
  if (status?.needs_setup) return <Navigate to="/setup" replace />
  if (status?.user) return <Navigate to={status.user.must_change_password ? '/change-password' : '/'} replace />

  const from = (location.state as { from?: string } | null)?.from ?? '/'
  const submit = (e: FormEvent) => {
    e.preventDefault()
    login.mutate({ email, password }, {
      onSuccess: (user) => navigate(user.must_change_password ? '/change-password' : from, { replace: true }),
    })
  }

  return (
    <AuthFrame title="Log in to Athena">
      <form onSubmit={submit} className="grid gap-4">
        <Field label="Email">
          <input type="email" autoComplete="username" autoFocus required value={email} onChange={(e) => setEmail(e.target.value)} className={fieldClass} />
        </Field>
        <Field label="Password">
          <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} className={fieldClass} />
        </Field>
        {login.isError && <p className="text-[12.5px] text-bad" role="alert">{apiErrorMessage(login.error, 'You could not be logged in.')}</p>}
        <Button type="submit" variant="primary" className="h-9" disabled={login.isPending}>
          {login.isPending ? 'Logging in…' : 'Log in'}
        </Button>
        <p className="text-center text-[12px] text-fg-3">No account, or forgot your password? Ask your Athena admin.</p>
      </form>
    </AuthFrame>
  )
}

/** The very first visit: whoever creates this account is the admin. */
export function SetupPage() {
  const { data: status, isLoading } = useAuthStatus()
  const setup = useSetup()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  if (isLoading) return <Centered><Spinner label="Loading…" /></Centered>
  if (!status?.needs_setup) return <Navigate to="/login" replace />

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setup.mutate({ email, display_name: name, password }, { onSuccess: () => navigate('/', { replace: true }) })
  }

  return (
    <AuthFrame title="Welcome to Athena" description="Create the admin account. You can add everyone else afterwards in Settings → Users.">
      <form onSubmit={submit} className="grid gap-4">
        <Field label="Your name">
          <input autoComplete="name" autoFocus required maxLength={80} value={name} onChange={(e) => setName(e.target.value)} className={fieldClass} />
        </Field>
        <Field label="Email">
          <input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} className={fieldClass} />
        </Field>
        <Field label="Password" hint={`At least ${MIN_PASSWORD} characters.`}>
          <input type="password" autoComplete="new-password" required minLength={MIN_PASSWORD} value={password} onChange={(e) => setPassword(e.target.value)} className={fieldClass} />
        </Field>
        {setup.isError && <p className="text-[12.5px] text-bad" role="alert">{apiErrorMessage(setup.error, 'The account could not be created.')}</p>}
        <Button type="submit" variant="primary" className="h-9" disabled={setup.isPending}>
          {setup.isPending ? 'Creating…' : 'Create admin account'}
        </Button>
      </form>
    </AuthFrame>
  )
}

/** Change your password: forced after a temporary one, and reused on the Account settings tab. */
export function PasswordForm({ onDone, submitLabel = 'Change password' }: { onDone?: () => void; submitLabel?: string }) {
  const change = useChangePassword()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [repeat, setRepeat] = useState('')
  const mismatch = repeat.length > 0 && next !== repeat

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (mismatch) return
    change.mutate({ current_password: current, new_password: next }, {
      onSuccess: () => {
        setCurrent('')
        setNext('')
        setRepeat('')
        onDone?.()
      },
    })
  }

  return (
    <form onSubmit={submit} className="grid gap-4">
      <Field label="Current password">
        <input type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} className={fieldClass} />
      </Field>
      <Field label="New password" hint={`At least ${MIN_PASSWORD} characters.`}>
        <input type="password" autoComplete="new-password" required minLength={MIN_PASSWORD} value={next} onChange={(e) => setNext(e.target.value)} className={fieldClass} />
      </Field>
      <Field label="New password again">
        <input type="password" autoComplete="new-password" required value={repeat} onChange={(e) => setRepeat(e.target.value)} className={fieldClass} aria-invalid={mismatch} />
      </Field>
      {mismatch && <p className="text-[12.5px] text-bad">The two new passwords differ.</p>}
      {change.isError && <p className="text-[12.5px] text-bad" role="alert">{apiErrorMessage(change.error, 'The password could not be changed.')}</p>}
      {change.isSuccess && !onDone && <p className="text-[12.5px] text-good">Password changed. Your other sessions were logged out.</p>}
      <Button type="submit" variant="primary" className="h-9" disabled={change.isPending || mismatch}>
        {change.isPending ? 'Saving…' : submitLabel}
      </Button>
    </form>
  )
}

/** After logging in with a temporary password, nothing else opens until it is replaced. */
export function ChangePasswordPage() {
  const { data: status, isLoading } = useAuthStatus()
  const logout = useLogout()
  const navigate = useNavigate()

  if (isLoading) return <Centered><Spinner label="Loading…" /></Centered>
  if (!status?.user) return <Navigate to="/login" replace />
  if (!status.user.must_change_password) return <Navigate to="/" replace />

  return (
    <AuthFrame title="Choose your password" description={`Signed in as ${status.user.email}. Replace the temporary password you were given.`}>
      <div className="grid gap-4">
        <Notice>Your admin can see a temporary password, so pick one only you know.</Notice>
        <PasswordForm submitLabel="Save and continue" onDone={() => navigate('/', { replace: true })} />
        <Button variant="ghost" onClick={() => logout.mutate(undefined, { onSettled: () => navigate('/login', { replace: true }) })}>
          Log out
        </Button>
      </div>
    </AuthFrame>
  )
}

function Centered({ children }: { children: ReactNode }) {
  return <div className="flex min-h-screen items-center justify-center bg-bg">{children}</div>
}

/** Pages inside the app shell need an account; send everyone else to setup, login or a password change. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { data: status, isLoading, isError } = useAuthStatus()
  const location = useLocation()

  if (isLoading) return <Centered><Spinner label="Loading…" /></Centered>
  if (isError || !status) {
    return (
      <Centered>
        <Notice tone="error" title="Athena's API is not answering" className="max-w-[420px]">
          Check that the API server is running, then reload the page.
        </Notice>
      </Centered>
    )
  }
  if (status.needs_setup) return <Navigate to="/setup" replace />
  if (!status.user) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  if (status.user.must_change_password) return <Navigate to="/change-password" replace />
  return <>{children}</>
}
