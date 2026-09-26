import { useCallback, useEffect, useRef, useState } from "react";
import { Authenticator } from "@aws-amplify/ui-react";
import { fetchAuthSession } from "aws-amplify/auth";
import "./photo-analysis.css";

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
  usefulLifeMonths: "",
  estimatedValueUsd: "",
  estimatedProductionDate: "",
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

function AssetApplication({ signOut, user }) {
  const [assets, setAssets] = useState([]);
  const [form, setForm] = useState(emptyAsset);
  const [message, setMessage] = useState("");
  const [query, setQuery] = useState("");
  const [saving, setSaving] = useState(false);
  const [photo, setPhoto] = useState(null);
  const [photoPreview, setPhotoPreview] = useState("");
  const [uploading, setUploading] = useState(false);
  const [photoMessage, setPhotoMessage] = useState("");
  const photoInput = useRef(null);
  const [analysis, setAnalysis] = useState(null);
  const [analysisMessage, setAnalysisMessage] = useState("");
  const [checkingAnalysis, setCheckingAnalysis] = useState(false);
  const [galleryItems, setGalleryItems] = useState([]);
  const [galleryLoading, setGalleryLoading] = useState(false);
  const [galleryMessage, setGalleryMessage] = useState("");
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
        return { ...asset, ...photoDetails };
      })
    );
    const visibleItems = results
      .filter((result) => result.status === "fulfilled")
      .map((result) => result.value);
    const failedCount = results.length - visibleItems.length;

    setGalleryItems(visibleItems);
    if (failedCount) {
      setGalleryMessage(
        `${failedCount} photograph${failedCount === 1 ? "" : "s"} could not be loaded. Refresh the gallery to try again.`
      );
    }
    setGalleryLoading(false);
  }, [assets]);

  useEffect(() => {
    loadGallery();
  }, [loadGallery]);

  useEffect(() => {
    if (!photo) {
      setPhotoPreview("");
      return undefined;
    }

    const previewUrl = URL.createObjectURL(photo);
    setPhotoPreview(previewUrl);

    return () => {
      URL.revokeObjectURL(previewUrl);
    };
  }, [photo]);

 useEffect(() => {
  return () => {

    if (analysisTimer.current) {
      clearTimeout(analysisTimer.current);
    }
  };
}, []);
  function updateField(event) {
    const { name, value } = event.target;
    setForm((current) => ({
      ...current,
      [name]:
        name === "usefulLifeMonths" || name === "estimatedValueUsd"
          ? value === ""
            ? ""
            : Number(value)
          : value,
    }));
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
    model: analysis.model || current.model,
    description: analysis.description || current.description,
    condition: analysis.condition || current.condition,
    usefulLifeMonths:
      analysis.usefulLifeMonths !== undefined &&
      analysis.usefulLifeMonths !== null
        ? Number(analysis.usefulLifeMonths)
        : current.usefulLifeMonths,
    estimatedValueUsd:
      analysis.estimatedValueUsd !== undefined &&
      analysis.estimatedValueUsd !== null
        ? Number(analysis.estimatedValueUsd)
        : current.estimatedValueUsd,
    estimatedProductionDate:
      analysis.estimatedProductionDate || current.estimatedProductionDate,
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
                type={
                  name.includes("Date")
                    ? "date"
                    : name === "usefulLifeMonths" ||
                        name === "estimatedValueUsd"
                      ? "number"
                      : "text"
                }
                onChange={updateField}
                required={[
                  "assetTag",
                  "description",
                  "purchaseDate",
                  "inServiceDate",
                  "purchaseValue",
                  "usefulLifeMonths",
                ].includes(name)}
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

{(photoPreview || checkingAnalysis || analysis) && (
  <div className="photo-analysis-grid">
    {photoPreview && (
      <article className="photo-preview-card">
        <h3>Selected photograph</h3>
        <img
          className="photo-preview-image"
          src={photoPreview}
          alt="Selected asset"
        />
        <p>{photo?.name}</p>
      </article>
    )}

    <article className="analysis-result">
      <h3>Bedrock suggestions</h3>

      {checkingAnalysis && (
        <p className="analysis-status">
          Bedrock is analyzing the photograph...
        </p>
      )}

      {!checkingAnalysis && !analysis && (
        <p>
          {form.imageKey
            ? "No AI suggestion is currently selected."
            : "Upload the photograph to start the AI analysis."}
        </p>
      )}

      {analysis && (
        <>
          <dl>
            <dt>Category</dt>
            <dd>{analysis.category || "—"}</dd>

            <dt>Suggested model</dt>
            <dd>{analysis.model || "Not identified"}</dd>

            <dt>Description</dt>
            <dd>{analysis.description || "—"}</dd>

            <dt>Condition</dt>
            <dd>{analysis.condition || "—"}</dd>

            <dt>Estimated useful life</dt>
            <dd>
              {analysis.usefulLifeMonths
                ? `${analysis.usefulLifeMonths} months`
                : "—"}
            </dd>

            <dt>Estimated value</dt>
            <dd>
              {analysis.estimatedValueUsd
                ? `$${Number(analysis.estimatedValueUsd).toLocaleString("en-US")}`
                : "—"}
            </dd>

            <dt>Maintenance category</dt>
            <dd>{analysis.maintenanceCategory || "—"}</dd>

            <dt>Estimated production date</dt>
            <dd>{analysis.estimatedProductionDate || "Not identified"}</dd>
          </dl>

          <div className="analysis-actions">
            <button type="button" onClick={applyAnalysis}>
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
        </>
      )}
    </article>
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
              Only photographs for assets authorized by your Cognito role are shown.
            </p>
          </div>
          <button
            type="button"
            className="secondary gallery-refresh"
            disabled={galleryLoading}
            onClick={loadGallery}
          >
            {galleryLoading ? "Loading..." : "Refresh gallery"}
          </button>
        </div>

        {galleryMessage && <div className="notice" role="status">{galleryMessage}</div>}
        {!galleryLoading && !galleryItems.length && (
          <p className="gallery-empty">No authorized assets with photographs were found.</p>
        )}

        <div className="asset-gallery" aria-busy={galleryLoading}>
          {galleryItems.map((asset) => {
            const suggestion = asset.suggestion;
            return (
              <article className="asset-photo-card" key={asset.assetId}>
                <img
                  className="asset-gallery-image"
                  src={asset.photoUrl}
                  alt={`${asset.assetTag} ${asset.category || "asset"}`}
                  loading="lazy"
                />
                <div className="asset-photo-content">
                  <div className="asset-photo-title">
                    <div>
                      <p className="asset-photo-tag">{asset.assetTag}</p>
                      <h3>{asset.category || "Uncategorized asset"}</h3>
                    </div>
                    <span className="status">{asset.status}</span>
                  </div>
                  <p>{asset.description || "No description provided."}</p>
                  <dl className="asset-photo-meta">
                    <dt>Department</dt>
                    <dd>{asset.department || "—"}</dd>
                    <dt>Condition</dt>
                    <dd>{asset.condition || "—"}</dd>
                  </dl>

                  <div className="gallery-analysis">
                    <div className="gallery-analysis-heading">
                      <h4>Bedrock insight</h4>
                      <span className={`analysis-badge analysis-${(asset.analysisStatus || "processing").toLowerCase()}`}>
                        {asset.analysisStatus || "Processing"}
                      </span>
                    </div>
                    {suggestion ? (
                      <dl>
                        <dt>Detected category</dt>
                        <dd>{suggestion.category || "—"}</dd>
                        <dt>Suggested model</dt>
                        <dd>{suggestion.model || "Not identified"}</dd>
                        <dt>Description</dt>
                        <dd>{suggestion.description || "—"}</dd>
                        <dt>Condition</dt>
                        <dd>{suggestion.condition || "—"}</dd>
                        <dt>Estimated useful life</dt>
                        <dd>
                          {suggestion.usefulLifeMonths
                            ? `${suggestion.usefulLifeMonths} months`
                            : "—"}
                        </dd>
                        <dt>Estimated value</dt>
                        <dd>
                          {suggestion.estimatedValueUsd
                            ? `$${Number(suggestion.estimatedValueUsd).toLocaleString("en-US")}`
                            : "—"}
                        </dd>
                        <dt>Estimated production date</dt>
                        <dd>{suggestion.estimatedProductionDate || "Not identified"}</dd>
                        <dt>Maintenance</dt>
                        <dd>{suggestion.maintenanceCategory || "—"}</dd>
                      </dl>
                    ) : (
                      <p>The AI analysis is still processing or has no suggestion.</p>
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
            <thead><tr><th>Tag</th><th>Category</th><th>Description</th><th>Department</th><th>Status</th></tr></thead>
            <tbody>
              {assets.map((asset) => (
                <tr key={asset.assetId}><td>{asset.assetTag}</td><td>{asset.category}</td><td>{asset.description}</td><td>{asset.department || "—"}</td><td><span className="status">{asset.status}</span></td></tr>
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
