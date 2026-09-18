"use client";

import Link from "next/link";
import {
  ArrowRight,
  BookOpenText,
  CheckCircle,
  Circle,
  FileText,
  GitBranch,
  LockKey,
  MagnifyingGlass,
  Quotes,
  ShieldCheck,
  SignIn,
  Sparkle,
  WindowsLogo,
} from "@phosphor-icons/react";

export default function Landing() {
  return (
    <div className="lp">
      <header className="lp-header">
        <div className="lp-wrap lp-nav">
          <div className="lp-brand">
            <span className="lp-dot" aria-hidden>
              <BookOpenText size={14} weight="fill" />
            </span>
            ActWise
          </div>
          <nav className="lp-links">
            <a href="#coverage">Coverage</a>
            <a href="#features">How it works</a>
            <a href="#security">Security</a>
          </nav>
          <div className="lp-navright">
            <Link className="lp-btn lp-ghost" href="/chat">
              <SignIn size={16} /> Sign in
            </Link>
            <Link className="lp-btn lp-primary" href="/chat">
              Open the assistant
            </Link>
          </div>
        </div>
      </header>

      <div className="lp-wrap">
        <section className="lp-hero">
          <div>
            <span className="lp-kicker">
              <Sparkle size={13} weight="fill" /> NICE Actimize documentation, answered
            </span>
            <h1 className="lp-h1">Every Actimize answer, grounded in the docs you can access.</h1>
            <p className="lp-lede">
              Ask about ActOne, SAM, IFM or CDD in plain language. ActWise searches the live
              documentation, answers with citations, and only ever shows what your DOCenter
              entitlements allow.
            </p>
            <div className="lp-cta-row">
              <Link className="lp-btn lp-primary lp-lg" href="/chat">
                <WindowsLogo size={17} weight="bold" /> Sign in with SSO
              </Link>
              <Link className="lp-btn lp-ghost lp-lg" href="/chat">
                Open the assistant <ArrowRight size={16} />
              </Link>
            </div>
            <div className="lp-subline">
              <ShieldCheck size={15} weight="fill" /> Single sign-on for Actimize employees. No new
              password.
            </div>
          </div>

          <div className="lp-preview" aria-hidden>
            <div className="lp-pv-q">Question</div>
            <div className="lp-pv-qt">What is the latest release of ActOne and what is new?</div>
            <div className="lp-pv-ans">
              <div className="lp-pv-rail" />
              <div className="lp-pv-body">
                <div className="lp-pv-meta">
                  <MagnifyingGlass size={13} /> Searched the documentation across 4 lookups
                </div>
                <p>
                  The latest release is <strong>ActOne 10.2</strong>. Key additions include the{" "}
                  <strong>Designer Console</strong> for self-service metadata, business-unit{" "}
                  <strong>confidential-data permissions</strong>, and edit or delete of work-item
                  notes.
                </p>
                <div className="lp-pv-src">
                  <FileText size={16} weight="fill" />
                  <div>
                    <div className="lp-pv-t">ActOne 10.2 Release Notes</div>
                    <div className="lp-pv-u">
                      docs.niceactimize.com/bundle/Actimize_ActOne_10.2_Release_Notes
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>
      </div>

      <div className="lp-coverage" id="coverage">
        <div className="lp-wrap lp-cov-in">
          <span className="lp-cov-lbl">COVERS</span>
          {["ActOne", "AML-SAM", "IFM", "CDD", "RCM"].map((p) => (
            <span key={p} className="lp-cov-p">
              <Circle size={9} weight="fill" /> {p}
            </span>
          ))}
          <span className="lp-cov-lbl">10.0 · 10.1 · 10.2</span>
        </div>
      </div>

      <div className="lp-wrap">
        <section className="lp-block" id="features">
          <h2 className="lp-h2">Built for how Actimize teams actually work.</h2>
          <p className="lp-plede">
            Not a general chatbot pointed at a PDF dump. ActWise reads the same documentation portal
            you do, respects the same access rules, and shows its sources every time.
          </p>

          <div className="lp-feat">
            <div className="lp-card">
              <div className="lp-ico">
                <Quotes size={20} weight="fill" />
              </div>
              <h3>Answers with citations</h3>
              <p>
                Every response links the exact documentation page it came from, so you can verify
                and go deeper in one click.
              </p>
            </div>
            <div className="lp-card">
              <div className="lp-ico">
                <LockKey size={20} weight="fill" />
              </div>
              <h3>Scoped to your entitlements</h3>
              <p>
                ActWise reads the portal as you. If your account cannot see a bundle, neither can
                your answers. No leakage across licenses.
              </p>
            </div>

            <div className="lp-card lp-span2">
              <div>
                <div className="lp-ico">
                  <GitBranch size={20} weight="fill" />
                </div>
                <h3>Version-aware retrieval</h3>
                <p>
                  Ask about a specific release and get release-specific answers. ActWise
                  distinguishes 10.2 from 10.2 SP1 and flags where features first appeared.
                </p>
              </div>
              <div className="lp-side">
                <div className="lp-kv">
                  <span className="k">10.2</span>
                  <span className="v">Designer Console, confidential-data permissions</span>
                </div>
                <div className="lp-kv">
                  <span className="k">10.2 SP1</span>
                  <span className="v">Edit / delete notes, new REST APIs</span>
                </div>
                <div className="lp-kv">
                  <span className="k">10.1</span>
                  <span className="v">Prior platform baseline</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="lp-block lp-tight" id="security">
          <div className="lp-band">
            <div className="lp-band-row">
              <div>
                <h2 className="lp-h2 lp-sm">Enterprise access, done right.</h2>
                <p className="lp-band-p">
                  Identity and entitlements are the whole point, not an afterthought. ActWise ties
                  your login to your real documentation access.
                </p>
              </div>
              <ul className="lp-band-list">
                <li>
                  <CheckCircle size={18} weight="fill" /> Microsoft SSO for employees, one click, no
                  new credential.
                </li>
                <li>
                  <CheckCircle size={18} weight="fill" /> Per-user documentation session, isolated
                  from every other user.
                </li>
                <li>
                  <CheckCircle size={18} weight="fill" /> Signed identity on every request between
                  the app and the docs service.
                </li>
              </ul>
            </div>
          </div>
        </section>

        <section className="lp-final">
          <h2>Stop hunting the docs. Ask instead.</h2>
          <p>Sign in with your Actimize account and get a cited answer in seconds.</p>
          <Link className="lp-btn lp-primary lp-lg" href="/chat">
            <WindowsLogo size={17} weight="bold" /> Sign in with SSO
          </Link>
        </section>
      </div>

      <footer className="lp-footer">
        <div className="lp-wrap lp-foot">
          <div className="lp-brand lp-brand-sm">
            <span className="lp-dot lp-dot-sm" aria-hidden>
              <BookOpenText size={11} weight="fill" />
            </span>
            ActWise
          </div>
          <div className="lp-foot-right">
            <span>NICE Actimize engineering</span>
            <span>Internal use</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
