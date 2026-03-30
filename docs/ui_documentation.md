# Athena UI Documentation

Athena's frontend is a high-performance, responsive research intelligence interface designed to aggregate and surface key AI trends, research papers, and industrial news.

## 🛠 Tech Stack

- **Core Framework**: React 19
- **Build Tool**: Vite 8
- **Language**: TypeScript
- **Styling**: Tailwind CSS 4
- **State Management**: Zustand
- **Data Fetching**: TanStack Query (React Query)
- **Icons**: Lucide React
- **Routing**: React Router DOM 7

---

## 🏗 Architecture & Layout

The application follows a standard SPA (Single Page Application) architecture with a global layout:

### **Global Layout (`components/Layout.tsx`)**
- **Sidebar**: Sticky navigation containing the logo, global search, and primary links.
- **Mobile Header**: Condensed header with a hamburger menu for smaller screens.
- **Main Area**: Scrollable region using `react-router-dom`'s `Outlet` for page components.
- **Related Sidebar**: A reactive component (`components/RelatedSidebar.tsx`) that surfaces contextually relevant items based on the current user focus.

---

## 📄 Pages

### **1. Feed (`pages/FeedPage.tsx`)**
The primary landing page. It displays a ranked list of research items and news. It supports:
- **Filtering**: By source (ArXiv, OpenAI, etc.) and category (Paper, Blog).
- **Infinite Scrolling**: Dynamically loads more content as the user scrolls.

### **2. Trending (`pages/TrendingPage.tsx`)**
Surfaces high-impact content with rapidly increasing citation counts or engagement signals.

### **3. Topics/Clusters (`pages/ClusterBrowserPage.tsx`)**
A bird’s-eye view of semantic clusters identified in the research landscape. Users can click into a topic to see all related content via `ClusterViewPage.tsx`.

### **4. Search (`pages/SearchResultsPage.tsx`)**
Displays results from semantic and keyword-based searches across the entire ingestion corpus.

### **5. Settings (`pages/SettingsPage.tsx`)**
Interface for managing user preferences, system configurations, and viewing background task statuses.

---

## 🧩 Core Components

### **Feed Card (`components/FeedCard.tsx`)**
The fundamental unit of information display.
- **Scoring Ring**: Displays a 0-100 score based on multi-signal ranking.
  - 🟢 **High (80+)**: Major breakthrough or high citation.
  - 🟡 **Mid (50-79)**: Relevant industry news/mid-tier research.
  - 🔴 **Low (<50)**: Standard updates.
- **AI Summary**: Shows a concise, system-generated summary (if processed).
- **Key Takeaways**: Expandable bullet points for rapid scanning.
- **Interactive Q&A**: Integrated trigger for the RAG Q&A system.

### **Q&A Panel (`components/QAPanel.tsx`)**
A reactive, interactive sidebar panel that allows users to ask natural language questions about specific content items, powered by the backend's RAG pipeline.

### **Score Tooltip (`components/ScoreTooltip.tsx`)**
Provides a detailed breakdown of how a content item was ranked (recency, citation velocity, source weight).

---

## 🎨 Design System

Athena uses a modern, high-contrast dark theme defined in `src/index.css`:

| Token | Value | Hex |
|-------|-------|-----|
| **Background** | zinc-950 | `#09090b` |
| **Card** | zinc-900 | `#18181b` |
| **Border** | zinc-800 | `#27272a` |
| **Accent Primary**| blue-500 | `#3b82f6` |
| **Text Primary** | zinc-100 | `#f4f4f5` |
| **Typography** | Inter | Sans-serif |

---

## 📱 User Interactions

- **Semantic Search**: Integrated via `SearchInput.tsx` in the sidebar.
- **Source Filtering**: Direct navigation to source-specific feeds.
- **Contextual Discovery**: Clicking on a "Cluster" label navigates to related research themes.
- **Responsive Design**: Fluidly transitions from wide desktop layouts to single-column mobile views.
