import {createBrowserRouter, Navigate} from "react-router-dom";
import {AppShell} from "./AppShell";
import {HomePage} from "./pages/HomePage";
import {StudyPage} from "./pages/StudyPage";
import {LibraryPage} from "./pages/LibraryPage";
import {JourneyPage} from "./pages/JourneyPage";
import {MorePage} from "./pages/MorePage";
import {DiagnosticPage} from "./pages/DiagnosticPage";
import {RemediationPage, RemediationScopePage} from "./pages/RemediationPage";
import {SessionPage} from "./pages/SessionPage";
import {MasteryPage, ObjectivePage} from "./pages/MasteryPage";
import {LearnPage, LessonPage} from "./pages/LearnPage";
import {RetentionPage} from "./pages/RetentionPage";
import {LabsPage} from "./pages/LabsPage";
import {PracticeExamPage, PracticeExamsPage} from "./pages/PracticeExamPage";
import {AnalyticsPage} from "./pages/AnalyticsPage";
import {TimelinePage} from "./pages/TimelinePage";
import {LearningRequestsPage} from "./pages/LearningRequestsPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      {index: true, element: <HomePage />},
      {path: "study", element: <StudyPage />},
      {path: "study/check/:scopeId", element: <DiagnosticPage />},
      {path: "study/remediate/:scopeId", element: <RemediationScopePage />},
      {path: "study/review/:objectiveId", element: <RetentionPage />},
      {path: "study/results/:attemptId", element: <RemediationPage />},
      {path: "session", element: <SessionPage />},
      {path: "mastery", element: <MasteryPage />},
      {path: "mastery/:objectiveId", element: <ObjectivePage />},
      {path: "learn", element: <LearnPage />},
      {path: "learn/:objectiveId", element: <LessonPage />},
      {path: "labs", element: <LabsPage />},
      {path: "practice", element: <PracticeExamsPage />},
      {path: "practice/:attemptId", element: <PracticeExamPage />},
      {path: "analytics", element: <AnalyticsPage />},
      {path: "library", element: <LibraryPage />},
      {path: "journey", element: <JourneyPage />},
      {path: "timeline", element: <TimelinePage />},
      {path: "more", element: <MorePage />},
      {path: "learning-requests", element: <LearningRequestsPage />},
      {path: "*", element: <Navigate to="/" replace />},
    ],
  },
], {basename: "/v2"});
