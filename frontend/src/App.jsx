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
  location: "",
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

// Mirrors the backend rules so the UI only offers actions the API will
// allow. The API remains the authority.
function useIdentity() {
  const [identity, setIdentity] = useState(null);

  useEffect(() => {
    let active = true;

    fetchAuthSession()
      .then((session) => {
        const payload = session.tokens?.idToken?.payload || {};

        if (active) {
          setIdentity({
            sub: payload.sub,
            groups: new Set(payload["cognito:groups"] || []),
            department: payload["custom:department"],
          });
        }
      })
      .catch(() => {
        if (active) setIdentity(null);
      });

    return () => {
      active = false;
    };
  }, []);

  return identity;
}

function formatMoney(value) {
  return value === undefined || value === null ? "—" : `$${value}`;
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
  const [editingMaintenance, setEditingMaintenance] =
    useState(null);
  const editingMaintenanceId =
    editingMaintenance?.maintenanceId ?? null;
  const identity = useIdentity();
  const isAdministrator =
    identity?.groups.has("Administrator") ?? false;

  function canEditMaintenance(item) {
    if (isAdministrator) return true;

    return Boolean(
      identity?.groups.has("Technician") &&
        identity.sub &&
        item.performedBy === identity.sub &&
        identity.department &&
        identity.department === asset.department
    );
  }

  const showMaintenanceActions =
    isAdministrator || history.some(canEditMaintenance);

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

  function maintenancePath(maintenanceId) {
    const base = `/assets/${encodeURIComponent(
      asset.assetId
    )}/maintenance`;

    return maintenanceId
      ? `${base}/${encodeURIComponent(maintenanceId)}`
      : base;
  }

  function editMaintenance(item) {
    setEditingMaintenance(item);
    setMaintenanceForm(
      Object.fromEntries(
        Object.keys(emptyMaintenance).map((key) => [
          key,
          item[key] ?? "",
        ])
      )
    );
    setMaintenanceMessage("");
  }

  function cancelEditMaintenance() {
    setEditingMaintenance(null);
    setMaintenanceForm(emptyMaintenance);
  }

  async function deleteMaintenance(item) {
    if (
      !window.confirm(
        `Delete the ${item.maintenanceType} record from ${item.performedDate}?`
      )
    ) {
      return;
    }

    setMaintenanceMessage("");

    try {
      const result = await api(
        maintenancePath(item.maintenanceId),
        { method: "DELETE" }
      );

      if (editingMaintenanceId === item.maintenanceId) {
        cancelEditMaintenance();
      }

      setMaintenanceMessage(result.message);
      await loadMaintenance();
    } catch (error) {
      setMaintenanceMessage(error.message);
    }
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

      if (editingMaintenance) {
        payload.expectedUpdatedAt =
          editingMaintenance.updatedAt ?? null;
      }

      const result = await api(
        maintenancePath(editingMaintenanceId),
        {
          method: editingMaintenanceId ? "PUT" : "POST",
          body: JSON.stringify(payload),
        }
      );

      setMaintenanceMessage(result.message);
      setMaintenanceForm(emptyMaintenance);
      setEditingMaintenance(null);
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
            <dt>Location</dt>
            <dd>{asset.location || "—"}</dd>
          </div>

          <div>
            <dt>In-service date</dt>
            <dd>{asset.inServiceDate || "—"}</dd>
          </div>
        </dl>
      </section>

      <section className="panel">
        <h2>Depreciation</h2>

        {asset.depreciation ? (
          <dl className="asset-summary">
            <div>
              <dt>Original purchase value</dt>
              <dd>
                {formatMoney(
                  asset.depreciation.originalPurchaseValue
                )}
              </dd>
            </div>

            <div>
              <dt>Annual depreciation</dt>
              <dd>
                {formatMoney(
                  asset.depreciation.annualDepreciation
                )}
              </dd>
            </div>

            <div>
              <dt>Accumulated depreciation</dt>
              <dd>
                {formatMoney(
                  asset.depreciation.accumulatedDepreciation
                )}
              </dd>
            </div>

            <div>
              <dt>Current book value</dt>
              <dd>
                {formatMoney(
                  asset.depreciation.currentBookValue
                )}
              </dd>
            </div>

            <div>
              <dt>Useful life consumed</dt>
              <dd>
                {`${asset.depreciation.usefulLifeConsumedPercent}%`}
              </dd>
            </div>

            <div>
              <dt>Estimated replacement date</dt>
              <dd>
                {asset.depreciation.estimatedReplacementDate}
              </dd>
            </div>
          </dl>
        ) : (
          <p>
            Depreciation is unavailable because the asset is
            missing financial or in-service information.
          </p>
        )}
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
        <h2>
          {editingMaintenanceId
            ? `Edit maintenance ${editingMaintenanceId}`
            : "Record maintenance"}
        </h2>

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
              : editingMaintenanceId
                ? "Save changes"
                : "Record maintenance"}
          </button>

          {editingMaintenanceId && (
            <button
              type="button"
              className="secondary"
              onClick={cancelEditMaintenance}
              disabled={savingMaintenance}
            >
              Cancel
            </button>
          )}
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
                {showMaintenanceActions && <th>Actions</th>}
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
                    {showMaintenanceActions && (
                      <td>
                        {canEditMaintenance(item) && (
                          <button
                            type="button"
                            className="secondary table-action"
                            onClick={() => editMaintenance(item)}
                          >
                            Edit
                          </button>
                        )}{" "}
                        {isAdministrator && (
                          <button
                            type="button"
                            className="secondary table-action"
                            onClick={() => deleteMaintenance(item)}
                          >
                            Delete
                          </button>
                        )}
                      </td>
                    )}
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={showMaintenanceActions ? 8 : 7}>
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
  const [nextToken, setNextToken] = useState(null);
  const [maintenanceAsset, setMaintenanceAsset] = useState(null);
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
  const activePhotoKey = useRef(null);
  const uploadToken = useRef(0);

  const loadAssets = useCallback(async ({
    append = false,
    token = null,
  } = {}) => {
    try {
      const params = new URLSearchParams();

      if (query) {
        params.set("q", query);
      }

      if (token) {
        params.set("nextToken", token);
      }

      const queryString = params.toString();
      const result = await api(
        `/assets${queryString ? `?${queryString}` : ""}`
      );

      setAssets((current) =>
        append ? [...current, ...result.items] : result.items
      );
      setNextToken(result.nextToken || null);
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

  activePhotoKey.current = null;
  uploadToken.current += 1;
  setPhoto(selected);
  setForm((current) => ({ ...current, imageKey: "" }));
  setPhotoMessage("");
  setAnalysis(null);
  setAnalysisMessage("");
  setCheckingAnalysis(false);
}

  async function checkPhotoAnalysis(photoKey, attempt = 0) {
  if (activePhotoKey.current !== photoKey) return;

  if (attempt === 0) {
    setCheckingAnalysis(true);
    setAnalysis(null);
  }

  try {
    const result = await api(
      `/photo-analysis?key=${encodeURIComponent(photoKey)}`
    );

    if (activePhotoKey.current !== photoKey) return;

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
    if (activePhotoKey.current !== photoKey) return;
    setAnalysisMessage(error.message);
    setCheckingAnalysis(false);
  }
}

    async function uploadPhoto() {
  if (!photo || uploading || saving) return;

  const token = uploadToken.current;

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

    if (uploadToken.current !== token) return;

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

    if (uploadToken.current !== token) return;

    setForm((current) => ({
      ...current,
      imageKey: signed.key,
    }));

    setPhotoMessage(
      "Photo uploaded privately. Bedrock analysis has started."
    );

    activePhotoKey.current = signed.key;
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
    manufacturer: analysis.manufacturer || current.manufacturer,
    model: analysis.model || current.model,
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
activePhotoKey.current = null;

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

      <dt>Manufacturer</dt>
      <dd>{analysis.manufacturer || "—"}</dd>

      <dt>Model</dt>
      <dd>{analysis.model || "—"}</dd>

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

        {nextToken && (
          <button
            className="secondary"
            onClick={() =>
              loadAssets({
                append: true,
                token: nextToken,
              })
            }
          >
            Load more
          </button>
        )}
      </section>
    </main>
  );
}

export default function App() {
  return <Authenticator>{({ signOut, user }) => <AssetApplication signOut={signOut} user={user} />}</Authenticator>;
}
