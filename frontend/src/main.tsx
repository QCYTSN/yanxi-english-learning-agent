import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import { App } from './App'
import { establishUiSession } from './api/client'
import './styles.css'
import './workspace.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 10_000, retry: 1 },
    mutations: { retry: 0 },
  },
})

async function start() {
  let startupError: Error | null = null
  try {
    await establishUiSession()
  } catch (error) {
    startupError = error instanceof Error ? error : new Error('Unable to connect to the local study service.')
  }
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <App startupError={startupError} />
        </BrowserRouter>
      </QueryClientProvider>
    </StrictMode>,
  )
}

void start()
