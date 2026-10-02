import { createContext, useContext } from 'react'

export const ParentContext = createContext(null)

/** Сессия кабинета: profile, children, child, selectChild, signIn, signOut, me (ParentSession.jsx). */
export function useParent() {
  return useContext(ParentContext)
}
