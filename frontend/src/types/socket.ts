import type {
  ClientToServerPayloads,
  ServerToClientPayloads,
} from './socket.generated'

type BuiltInServerEvents = {
  connect: () => void
  disconnect: (reason: string) => void
  connect_error: (error: Error) => void
}

export type ServerToClientEvents = BuiltInServerEvents & {
  [Event in keyof ServerToClientPayloads]: (
    data: ServerToClientPayloads[Event]
  ) => void
}

export type ClientToServerEvents = {
  [Event in keyof ClientToServerPayloads]: (
    data: ClientToServerPayloads[Event]
  ) => void
}
