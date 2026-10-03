import { useCallback, useEffect, useRef, useState } from "react";
import { Authenticator } from "@aws-amplify/ui-react";
import { fetchAuthSession } from "aws-amplify/auth";

const API_URL = import.meta.env.VITE_API_URL;

const emptyAsset = {
  assetTag: "",
  category: "Laptop",
  description: "",
  manufacturer: "",
  model: "",
  serialNumber: "",
  purchaseDate: "",
  inServiceDate: "",
  purchaseValue: "",
  salvageValue: "0.00",
  usefulLifeMonths: 48,
  department: "",
  assignedUserId: "",
  condition: "Good",
  status: "Available",
  imageKey: "",
};

async function api(path, options = {}) {
  const session = await fetchAuthSession();
  const token = session.tokens?.idToken?.toString();
  const result = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", Authorization: token, ...options.headers },
  });
  const body = await result.json();
  if (!result.ok) throw new Error(body.message || "Request failed");
  return body;
}

const emptyMaintenance = {
  maintenanceType: "Preventive",
  description: "",
  performedDate: "",
  conditionAfter: "",
  nextMaintenanceDate: "",
  cost: "0.00",
};

function MaintenancePage({
  asset,
  onBack,
  signOut,
  user,
}) {
  const [history, setHistory] = useState([]);
  const [schedule, setSchedule] = useState(null);
  const [aiRecommendation, setAiRecommendation] =
    useState(null);
  const [maintenanceForm, setMaintenanceForm] =
    useState(emptyMaintenance);
  const [loading, setLoading] = useState(true);
  const [savingMaintenance, setSavingMaintenance] =
    useState(false);
  const [generatingAi, setGeneratingAi] =
    useState(false);
  const [maintenanceMessage, setMaintenanceMessage] =
    useState("");

  const loadMaintenance = useCallback(async () => {
    setLoading(true);

    try {
      const result = await api(
        `/assets/${encodeURIComponent(
          asset.assetId
        )}/maintenance`
      );

      setHistory(result.items || []);
      setSchedule(result.recommendation || null);
      setMaintenanceMessage("");
    } catch (error) {
      setMaintenanceMessage(error.message);
    } finally {
      setLoading(false);
    }
  }, [asset.assetId]);

  useEffect(() => {
    loadMaintenance();
  }, [loadMaintenance]);

  function updateMaintenanceField(event) {
    const { name, value } = event.target;

    setMaintenanceForm((current) => ({
      ...current,
      [name]: value,
    }));
  }

  async function recordMaintenance(event) {
    event.preventDefault();

    if (savingMaintenance) return;

    setSavingMaintenance(true);
    setMaintenanceMessage("");

    try {
      const payload = Object.fromEntries(
        Object.entries(maintenanceForm).map(
          ([key, value]) => [
            key,
            value === "" ? null : value,
          ]
        )
      );

      const result = await api(
        `/assets/${encodeURIComponent(
          asset.assetId
        )}/maintenance`,
        {
          method: "POST",
          body: JSON.stringify(payload),
        }
      );

      setMaintenanceMessage(result.message);
      setMaintenanceForm(emptyMaintenance);
      setAiRecommendation(null);
      await loadMaintenance();
    } catch (error) {
      setMaintenanceMessage(error.message);
    } finally {
      setSavingMaintenance(false);
    }
  }

  async function generateAiRecommendation() {
    if (generatingAi) return;

    setGeneratingAi(true);
    setMaintenanceMessage("");

    try {
      const result = await api(
        `/assets/${encodeURIComponent(
          asset.assetId
        )}/maintenance-recommendation`,
        {
          method: "POST",
        }
      );

      setSchedule(result.schedule || null);
      setAiRecommendation(
        result.aiRecommendation || null
      );
      setMaintenanceMessage( "" );
    } catch (error) {
      setMaintenanceMessage(error.message);
    } finally {
      setGeneratingAi(false);
    }
  }

  return (
    <main>
      <header>
        <div>
          <p className="eyebrow">
            MAINTENANCE INTELLIGENCE
          </p>
          <h1>Maintenance history and recommendations</h1>
          <p>
            Signed in as{" "}
            {user?.signInDetails?.loginId}
          </p>
        </div>

        <div className="header-actions">
          <button
            type="button"
            className="secondary"
            onClick={onBack}
          >
            Back to inventory
          </button>

          <button
            type="button"
            className="secondary"
            onClick={signOut}
          >
            Sign out
          </button>
        </div>
      </header>

      {maintenanceMessage && (
        <div className="notice" role="status">
          {maintenanceMessage}
        </div>
      )}

      <section className="panel">
        <div className="section-heading">
          <div>
            <h2>{asset.assetTag}</h2>
            <p>{asset.description}</p>
          </div>

          <span className="status">
            {asset.status || "Unknown"}
          </span>
        </div>

        <dl className="asset-summary">
          <div>
            <dt>Asset ID</dt>
            <dd>{asset.assetId}</dd>
          </div>

          <div>
            <dt>Category</dt>
            <dd>{asset.category || "—"}</dd>
          </div>

          <div>
            <dt>Condition</dt>
            <dd>{asset.condition || "—"}</dd>
          </div>

          <div>
            <dt>In-service date</dt>
            <dd>{asset.inServiceDate || "—"}</dd>
          </div>

          <div>
            <dt>Current book value</dt>
            <dd>
              {asset.depreciation?.currentBookValue
                ? `$${asset.depreciation.currentBookValue}`
                : "—"}
            </dd>
          </div>

          <div>
            <dt>Replacement date</dt>
            <dd>
              {asset.depreciation
                ?.estimatedReplacementDate || "—"}
            </dd>
          </div>
        </dl>
      </section>

      <section className="maintenance-grid">
        <article className="panel">
          <div className="section-heading">
            <h2>Calculated schedule</h2>

            {schedule?.maintenanceStatus && (
              <span
                className={`maintenance-status maintenance-${schedule.maintenanceStatus.toLowerCase()}`}
              >
                {schedule.maintenanceStatus}
              </span>
            )}
          </div>

          {loading ? (
            <p>Loading maintenance schedule...</p>
          ) : schedule ? (
            <dl className="recommendation-details">
              <dt>Priority</dt>
              <dd>{schedule.priority || "—"}</dd>

              <dt>Recommended cleaning</dt>
              <dd>
                {schedule.recommendedCleaningDate || "—"}
              </dd>

              <dt>Recommended maintenance</dt>
              <dd>
                {schedule.recommendedMaintenanceDate ||
                  "—"}
              </dd>

              <dt>Days until maintenance</dt>
              <dd>
                {schedule.daysUntilMaintenance ??
                  "—"}
              </dd>

              <dt>Recommendation</dt>
              <dd>
                {schedule.recommendation ||
                  schedule.message ||
                  "—"}
              </dd>
            </dl>
          ) : (
            <p>No schedule is available.</p>
          )}
        </article>

        <article className="panel">
          <div className="section-heading">
            <h2>Bedrock recommendation</h2>

            <button
              type="button"
              onClick={generateAiRecommendation}
              disabled={generatingAi}
            >
              {generatingAi
                ? "Generating..."
                : "Generate recommendation"}
            </button>
          </div>

          {aiRecommendation ? (
            <div className="ai-maintenance-result">
              <dl className="recommendation-details">
                <dt>Risk level</dt>
                <dd>{aiRecommendation.riskLevel}</dd>

                <dt>Review status</dt>
                <dd>
                  {aiRecommendation.reviewStatus}
                </dd>

                <dt>Rationale</dt>
                <dd>{aiRecommendation.rationale}</dd>
              </dl>

              <h3>Recommended actions</h3>

              <ol>
                {aiRecommendation.recommendedActions.map(
                  (action) => (
                    <li key={action}>{action}</li>
                  )
                )}
              </ol>


            </div>
          ) : (
            <p>
              Generate an AI-assisted recommendation using
              the asset condition, maintenance history, and
              calculated schedule.
            </p>
          )}
        </article>
      </section>

      <section className="panel">
        <h2>Record maintenance</h2>

        <form
          className="maintenance-form"
          onSubmit={recordMaintenance}
        >
          <label>
            <span>Maintenance type</span>
            <select
              name="maintenanceType"
              value={maintenanceForm.maintenanceType}
              onChange={updateMaintenanceField}
            >
              <option>Preventive</option>
              <option>Corrective</option>
              <option>Inspection</option>
              <option>Cleaning</option>
              <option>Repair</option>
            </select>
          </label>

          <label>
            <span>Performed date</span>
            <input
              type="date"
              name="performedDate"
              value={maintenanceForm.performedDate}
              onChange={updateMaintenanceField}
              required
            />
          </label>

          <label>
            <span>Condition after maintenance</span>
            <select
              name="conditionAfter"
              value={maintenanceForm.conditionAfter}
              onChange={updateMaintenanceField}
            >
              <option value="">Not recorded</option>
              <option>Excellent</option>
              <option>Good</option>
              <option>Fair</option>
              <option>Poor</option>
              <option>Damaged</option>
            </select>
          </label>

          <label>
            <span>Next maintenance date</span>
            <input
              type="date"
              name="nextMaintenanceDate"
              value={
                maintenanceForm.nextMaintenanceDate
              }
              onChange={updateMaintenanceField}
            />
          </label>

          <label>
            <span>Cost</span>
            <input
              type="number"
              min="0"
              step="0.01"
              name="cost"
              value={maintenanceForm.cost}
              onChange={updateMaintenanceField}
            />
          </label>

          <label className="maintenance-description">
            <span>Description</span>
            <textarea
              name="description"
              value={maintenanceForm.description}
              onChange={updateMaintenanceField}
              required
              rows="4"
            />
          </label>

          <button
            type="submit"
            disabled={savingMaintenance}
          >
            {savingMaintenance
              ? "Saving..."
              : "Record maintenance"}
          </button>
        </form>
      </section>

      <section className="panel">
        <div className="section-heading">
          <h2>Maintenance history</h2>

          <button
            type="button"
            className="secondary"
            onClick={loadMaintenance}
            disabled={loading}
          >
            Refresh
          </button>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Type</th>
                <th>Description</th>
                <th>Condition after</th>
                <th>Next maintenance</th>
                <th>Cost</th>
                <th>Performed by</th>
              </tr>
            </thead>

            <tbody>
              {history.length ? (
                history.map((item) => (
                  <tr key={item.maintenanceId}>
                    <td>{item.performedDate || "—"}</td>
                    <td>
                      {item.maintenanceType || "—"}
                    </td>
                    <td>{item.description || "—"}</td>
                    <td>
                      {item.conditionAfter || "—"}
                    </td>
                    <td>
                      {item.nextMaintenanceDate || "—"}
                    </td>
                    <td>
                      {item.cost !== undefined
                        ? `$${item.cost}`
                        : "—"}
                    </td>
                    <td>
                      {item.performedByEmail ||
                        item.performedBy ||
                        "—"}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan="7">
                    {loading
                      ? "Loading maintenance history..."
                      : "No maintenance history has been recorded."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}

function AssetApplication({ signOut, user }) {
  const [assets, setAssets] = useState([]);
    const [maintenanceAsset, setMaintenanceAsset] =
    useState(null);
  const [form, setForm] = useState(emptyAsset);
  const [message, setMessage] = useState("");
  const [query, setQuery] = useState("");
  const [saving, setSaving] = useState(false);
  const [photo, setPhoto] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [photoMessage, setPhotoMessage] = useState("");
    const [galleryItems, setGalleryItems] = useState([]);
  const [galleryLoading, setGalleryLoading] = useState(false);
  const [galleryMessage, setGalleryMessage] = useState("");
  const photoInput = useRef(null);
  const [analysis, setAnalysis] = useState(null);
  const [analysisMessage, setAnalysisMessage] = useState("");
  const [checkingAnalysis, setCheckingAnalysis] = useState(false);
  const analysisTimer = useRef(null);

  const loadAssets = useCallback(async () => {
    try {
      const result = await api(`/assets${query ? `?q=${encodeURIComponent(query)}` : ""}`);
      setAssets(result.items);
      setMessage("");
    } catch (error) {
      setMessage(error.message);
    }
  }, [query]);

    useEffect(() => {
    loadAssets();
  }, [loadAssets]);

    const loadGallery = useCallback(async () => {
    const photoAssets = assets.filter((asset) => asset.imageKey);

    if (!photoAssets.length) {
      setGalleryItems([]);
      setGalleryMessage("");
      return;
    }

    setGalleryLoading(true);
    setGalleryMessage("");

    const results = await Promise.allSettled(
      photoAssets.map(async (asset) => {
        const photoDetails = await api(
          `/assets/${encodeURIComponent(asset.assetId)}/photo`
        );

        return {
          ...asset,
          ...photoDetails,
        };
      })
    );

    const visibleItems = results
      .filter((result) => result.status === "fulfilled")
      .map((result) => result.value);

    const failedCount =
      results.length - visibleItems.length;

    setGalleryItems(visibleItems);

    if (failedCount) {
      setGalleryMessage(
        `${failedCount} photograph${
          failedCount === 1 ? "" : "s"
        } could not be loaded. Refresh the gallery to try again.`
      );
    }

    setGalleryLoading(false);
  }, [assets]);

  useEffect(() => {
    loadGallery();
  }, [loadGallery]);

  useEffect(() => {
    return () => {
      if (analysisTimer.current) {
        clearTimeout(analysisTimer.current);
      }
    };
  }, []);

  function updateField(event) {
    const { name, value } = event.target;
    setForm((current) => ({ ...current, [name]: name === "usefulLifeMonths" ? Number(value) : value }));
  }

  function selectPhoto(event) {
  const selected = event.target.files?.[0] || null;

  if (analysisTimer.current) {
    clearTimeout(analysisTimer.current);
    analysisTimer.current = null;
  }

  setPhoto(selected);
  setForm((current) => ({ ...current, imageKey: "" }));
  setPhotoMessage("");
  setAnalysis(null);
  setAnalysisMessage("");
  setCheckingAnalysis(false);
}

  async function checkPhotoAnalysis(photoKey, attempt = 0) {
  if (attempt === 0) {
    setCheckingAnalysis(true);
    setAnalysis(null);
  }

  try {
    const result = await api(
      `/photo-analysis?key=${encodeURIComponent(photoKey)}`
    );

    if (result.status === "Processing") {
      if (attempt >= 30) {
        setAnalysisMessage(
          "Analysis is taking longer than expected. You may continue entering the asset details."
        );
        setCheckingAnalysis(false);
        return;
      }

      setAnalysisMessage("Bedrock is analyzing the photograph...");

      analysisTimer.current = setTimeout(() => {
        checkPhotoAnalysis(photoKey, attempt + 1);
      }, 2000);

      return;
    }

    if (result.status === "Ready" && result.suggestion) {
      setAnalysis(result.suggestion);
      setAnalysisMessage(
        "Bedrock analysis is ready. Review the suggestions before applying them."
      );
      setCheckingAnalysis(false);
      return;
    }

    setAnalysisMessage(
      result.message || "The photograph analysis could not be completed."
    );
    setCheckingAnalysis(false);
  } catch (error) {
    setAnalysisMessage(error.message);
    setCheckingAnalysis(false);
  }
}

    async function uploadPhoto() {
  if (!photo || uploading || saving) return;

  if (
    !["image/jpeg", "image/png"].includes(photo.type) ||
    photo.size < 1 ||
    photo.size > 3_750_000
  ) {
    setPhotoMessage(
      "Choose a JPEG or PNG photo between 1 byte and 3.75 MB."
    );
    return;
  }

  setUploading(true);
  setPhotoMessage("");
  setAnalysis(null);
  setAnalysisMessage("");

  try {
    const signed = await api("/photo-uploads", {
      method: "POST",
      body: JSON.stringify({
        contentType: photo.type,
      }),
    });

    const data = new FormData();

    Object.entries(signed.fields).forEach(
      ([name, value]) => data.append(name, value)
    );

    data.append("file", photo);

    const upload = await fetch(signed.url, {
      method: "POST",
      body: data,
    });

    if (!upload.ok) {
      throw new Error(
        "Photo upload failed. Please try again."
      );
    }

    setForm((current) => ({
      ...current,
      imageKey: signed.key,
    }));

    setPhotoMessage(
      "Photo uploaded privately. Bedrock analysis has started."
    );

    await checkPhotoAnalysis(signed.key);
  } catch (error) {
    setPhotoMessage(error.message);
    setCheckingAnalysis(false);
  } finally {
    setUploading(false);
  }
}
function applyAnalysis() {
  if (!analysis) return;

  setForm((current) => ({
    ...current,
    category: analysis.category || current.category,
    description: analysis.description || current.description,
    condition: analysis.condition || current.condition,
    usefulLifeMonths:
      analysis.usefulLifeMonths !== undefined
        ? Number(analysis.usefulLifeMonths)
        : current.usefulLifeMonths,
  }));

  setAnalysisMessage(
    "AI suggestions applied. Review or edit the values before creating the asset."
  );
}

function rejectAnalysis() {
  setAnalysis(null);
  setAnalysisMessage(
    "AI suggestions rejected. Enter the asset information manually."
  );
}
  async function createAsset(event) {
    event.preventDefault();
    if (saving || uploading) return;
    if (photo && !form.imageKey) {
      setPhotoMessage("Upload the selected photo first, or remove it to create the asset without a photo.");
      return;
    }
    setSaving(true);

    try {
      const payload = Object.fromEntries(Object.entries(form).map(([key, value]) => [key, value === "" ? null : value]));
      const result = await api("/assets", { method: "POST", body: JSON.stringify(payload) });
      setMessage(`${result.message} ID: ${result.assetId}`);
      setForm(emptyAsset);
      setPhoto(null);
      setAnalysis(null);
setAnalysisMessage("");
setCheckingAnalysis(false);

if (analysisTimer.current) {
  clearTimeout(analysisTimer.current);
  analysisTimer.current = null;
}
      if (photoInput.current) photoInput.current.value = "";
      setPhotoMessage("");
      await loadAssets();
    } catch (error) {
      setMessage(error.message);
    } finally {
      setSaving(false);
    }
  }
if (maintenanceAsset) {
    return (
      <MaintenancePage
        asset={maintenanceAsset}
        user={user}
        signOut={signOut}
        onBack={() => setMaintenanceAsset(null)}
      />
    );
  }

  return (
    <main>
      <header>
        <div>
          <p className="eyebrow">AWS CLOUD SECURITY PORTFOLIO</p>
          <h1>Smart Asset Lifecycle Tracker</h1>
          <p>Signed in as {user?.signInDetails?.loginId}</p>
        </div>
        <button className="secondary" onClick={signOut}>Sign out</button>
      </header>

      {message && <div className="notice" role="status">{message}</div>}

      <section className="panel">
        <h2>Register an asset manually</h2>
        <form onSubmit={createAsset}>
          {Object.entries(form).filter(([name]) => name !== "imageKey").map(([name, value]) => (
            <label key={name}>
              <span>{name.replace(/([A-Z])/g, " $1")}</span>
              <input
                name={name}
                value={value ?? ""}
                type={name.includes("Date") ? "date" : name === "usefulLifeMonths" ? "number" : "text"}
                onChange={updateField}
                required={["assetTag", "description", "purchaseDate", "inServiceDate", "purchaseValue"].includes(name)}
              />
            </label>
          ))}
          <div className="photo-upload">
            <label htmlFor="asset-photo"><span>Asset photo (optional)</span></label>
            <input id="asset-photo" ref={photoInput} type="file" accept="image/jpeg,image/png" disabled={uploading || saving} onChange={selectPhoto} />
            <button type="button" className="secondary" disabled={!photo || uploading || saving} onClick={uploadPhoto}>
              {uploading ? "Uploading..." : "Upload photo"}
            </button>
            {photoMessage && <p role="status">{photoMessage}</p>}
            {analysisMessage && (
  <p role="status">{analysisMessage}</p>
)}

{checkingAnalysis && (
  <p className="analysis-status">
    Analyzing photograph...
  </p>
)}

{analysis && (
  <div className="analysis-result">
    <h3>Bedrock suggestions</h3>

    <dl>
      <dt>Category</dt>
      <dd>{analysis.category || "—"}</dd>

      <dt>Description</dt>
      <dd>{analysis.description || "—"}</dd>

      <dt>Condition</dt>
      <dd>{analysis.condition || "—"}</dd>

      <dt>Useful life</dt>
      <dd>
        {analysis.usefulLifeMonths
          ? `${analysis.usefulLifeMonths} months`
          : "—"}
      </dd>

      <dt>Maintenance category</dt>
      <dd>{analysis.maintenanceCategory || "—"}</dd>

      <dt>Review status</dt>
      <dd>{analysis.reviewStatus || "—"}</dd>
    </dl>

    <div className="analysis-actions">
      <button
        type="button"
        onClick={applyAnalysis}
      >
        Apply suggestions
      </button>

      <button
        type="button"
        className="secondary"
        onClick={rejectAnalysis}
      >
        Reject suggestions
      </button>
    </div>
  </div>
)}
          </div>
          <button type="submit" disabled={saving || uploading}>
            {saving ? "Creating..." : "Create asset"}
          </button>
        </form>
      </section>
            <section className="panel gallery-panel">
        <div className="section-heading">
          <div>
            <h2>Asset photo gallery</h2>
            <p className="gallery-intro">
              Only photographs for assets authorized by your Cognito
              role are shown.
            </p>
          </div>

          <button
            type="button"
            className="secondary gallery-refresh"
            disabled={galleryLoading}
            onClick={loadGallery}
          >
            {galleryLoading
              ? "Loading..."
              : "Refresh gallery"}
          </button>
        </div>

        {galleryMessage && (
          <div className="notice" role="status">
            {galleryMessage}
          </div>
        )}

        {!galleryLoading && !galleryItems.length && (
          <p className="gallery-empty">
            No authorized assets with photographs were found.
          </p>
        )}

        <div
          className="asset-gallery"
          aria-busy={galleryLoading}
        >
          {galleryItems.map((asset) => {
            const suggestion = asset.suggestion;

            return (
              <article
                className="asset-photo-card"
                key={asset.assetId}
              >
                <img
                  className="asset-gallery-image"
                  src={asset.photoUrl}
                  alt={`${asset.assetTag} ${
                    asset.category || "asset"
                  }`}
                  loading="lazy"
                />

                <div className="asset-photo-content">
                  <div className="asset-photo-title">
                    <div>
                      <p className="asset-photo-tag">
                        {asset.assetTag}
                      </p>
                      <h3>
                        {asset.category ||
                          "Uncategorized asset"}
                      </h3>
                    </div>

                    <span className="status">
                      {asset.status}
                    </span>
                  </div>

                  <p>
                    {asset.description ||
                      "No description provided."}
                  </p>

                  <dl className="asset-photo-meta">
                    <dt>Department</dt>
                    <dd>{asset.department || "—"}</dd>

                    <dt>Condition</dt>
                    <dd>{asset.condition || "—"}</dd>
                  </dl>

                  <div className="gallery-analysis">
                    <div className="gallery-analysis-heading">
                      <h4>Bedrock insight</h4>
                      <span className="analysis-badge">
                        {asset.analysisStatus ||
                          "Processing"}
                      </span>
                    </div>

                    {suggestion ? (
                      <dl>
                        <dt>Detected category</dt>
                        <dd>
                          {suggestion.category || "—"}
                        </dd>

                        <dt>Description</dt>
                        <dd>
                          {suggestion.description || "—"}
                        </dd>

                        <dt>Maintenance</dt>
                        <dd>
                          {suggestion.maintenanceCategory ||
                            "—"}
                        </dd>

                        <dt>Review</dt>
                        <dd>
                          {suggestion.reviewStatus ||
                            "Needs review"}
                        </dd>
                      </dl>
                    ) : (
                      <p>
                        The AI analysis is still processing or
                        has no suggestion.
                      </p>
                    )}
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      </section>

      <section className="panel">
        <div className="section-heading">
          <h2>Authorized inventory</h2>

          <div className="search">
            <input aria-label="Search assets" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search tag or description" />
            <button className="secondary" onClick={loadAssets}>Search</button>
          </div>
        </div>
        <div className="table-wrap">
          <table>
  <thead>
    <tr>
      <th>Tag</th>
      <th>Category</th>
      <th>Description</th>
      <th>Department</th>
      <th>Status</th>
      <th>Maintenance</th>
    </tr>
  </thead>

  <tbody>
    {assets.map((asset) => (
      <tr key={asset.assetId}>
        <td>{asset.assetTag}</td>
        <td>{asset.category}</td>
        <td>{asset.description}</td>
        <td>{asset.department || "—"}</td>
        <td>
          <span className="status">
            {asset.status}
          </span>
        </td>
        <td>
          <button
            type="button"
            className="secondary table-action"
            onClick={() => setMaintenanceAsset(asset)}
          >
            View maintenance
          </button>
        </td>
      </tr>
    ))}
  </tbody>
</table>
        </div>
      </section>
    </main>
  );
}

export default function App() {
  return <Authenticator>{({ signOut, user }) => <AssetApplication signOut={signOut} user={user} />}</Authenticator>;
}
