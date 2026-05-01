import {
  GoogleAuthProvider,
  type User,
  createUserWithEmailAndPassword,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  signInWithPopup,
  signOut as firebaseSignOut,
  updateProfile,
} from "firebase/auth";
import { createContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { auth } from "../lib/firebase";

/**
 * Auth context — wraps every page that needs to read or change the
 * current user. Two consumers:
 *   - `useAuth()` hook for components
 *   - `<ProtectedRoute>` / `<PublicOnlyRoute>` for routing
 *
 * The provider listens to Firebase's onAuthStateChanged so `user` is
 * always live with whatever Firebase thinks. `loading` is true only
 * during the first auth-state determination on mount; subsequent
 * sign-in/out flips happen synchronously in callers, not via loading.
 */

export interface AuthContextValue {
  user: User | null;
  loading: boolean;
  error: string | null;
  signUp: (email: string, password: string, displayName: string) => Promise<User>;
  signIn: (email: string, password: string) => Promise<User>;
  signInWithGoogle: () => Promise<User>;
  signOut: () => Promise<void>;
  clearError: () => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

interface ProviderProps {
  children: ReactNode;
}

export function AuthProvider({ children }: ProviderProps) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, (next) => {
      setUser(next);
      setLoading(false);
    });
    return unsubscribe;
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      loading,
      error,
      clearError: () => setError(null),

      async signUp(email, password, displayName) {
        setError(null);
        try {
          const cred = await createUserWithEmailAndPassword(auth, email, password);
          if (displayName) {
            await updateProfile(cred.user, { displayName });
          }
          return cred.user;
        } catch (e) {
          setError(mapFirebaseError(e));
          throw e;
        }
      },

      async signIn(email, password) {
        setError(null);
        try {
          const cred = await signInWithEmailAndPassword(auth, email, password);
          return cred.user;
        } catch (e) {
          setError(mapFirebaseError(e));
          throw e;
        }
      },

      async signInWithGoogle() {
        setError(null);
        try {
          const provider = new GoogleAuthProvider();
          const cred = await signInWithPopup(auth, provider);
          return cred.user;
        } catch (e) {
          setError(mapFirebaseError(e, { context: "google" }));
          throw e;
        }
      },

      async signOut() {
        await firebaseSignOut(auth);
      },
    }),
    [user, loading, error],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// -- friendly Firebase error mapping --------------------------------------

interface MapOpts {
  context?: "google" | "email";
}

function mapFirebaseError(e: unknown, opts: MapOpts = {}): string {
  const code = (e as { code?: string } | null)?.code ?? "";
  if (opts.context === "google") {
    switch (code) {
      case "auth/popup-closed-by-user":
        // User cancelled. Not an error worth surfacing — clearError
        // immediately so the toast doesn't render. The throw still
        // happens so the caller can avoid a redirect.
        return "";
      case "auth/popup-blocked":
        return "Please allow popups to sign in with Google.";
      case "auth/account-exists-with-different-credential":
        return "This email is already registered with a password. Sign in with email instead.";
      case "auth/network-request-failed":
        return "Network error. Check your connection and try again.";
      default:
        return "Couldn't sign you in with Google. Please try again.";
    }
  }
  switch (code) {
    case "auth/email-already-in-use":
      return "An account with this email already exists. Try signing in instead.";
    case "auth/invalid-email":
      return "That doesn't look like a valid email address.";
    case "auth/weak-password":
      return "Password must be at least 8 characters.";
    case "auth/invalid-credential":
    case "auth/wrong-password":
    case "auth/user-not-found":
      return "That email and password don't match. Try again or create an account.";
    case "auth/too-many-requests":
      return "Too many attempts. Try again in a few minutes.";
    case "auth/network-request-failed":
      return "Network error. Check your connection and try again.";
    default:
      return "Something went wrong. Please try again.";
  }
}
