import React from "react";
import ReactDOM from "react-dom/client";
import { Amplify } from "aws-amplify";
import "@aws-amplify/ui-react/styles.css";
import App from "./App.jsx";
import "./styles.css";

Amplify.configure({
  Auth: {
    Cognito: {
      userPoolId: import.meta.env.VITE_USER_POOL_ID,
      userPoolClientId: import.meta.env.VITE_USER_POOL_CLIENT_ID,
      loginWith: {
  email: true,
  oauth: {
    domain:
      "smart-asset-tracker-ema-6007534.auth.us-east-1.amazoncognito.com",
    scopes: ["openid", "email", "profile"],
    redirectSignIn: [
      window.location.hostname === "localhost"
        ? "http://localhost:5173/"
        : "https://main.dx980x98nt3d5.amplifyapp.com/",
    ],
    redirectSignOut: [
      window.location.hostname === "localhost"
        ? "http://localhost:5173/"
        : "https://main.dx980x98nt3d5.amplifyapp.com/",
    ],
    responseType: "code",
  },
},
    },
  },
});

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

