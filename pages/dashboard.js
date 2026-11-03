import { useEffect, useState } from 'react';
import Head from 'next/head';
import { useRouter } from 'next/router';
import { onAuthStateChanged, signOut } from 'firebase/auth';
import { doc, getDoc, updateDoc } from 'firebase/firestore';
import { auth, db } from '../lib/firebase';

export default function Dashboard() {
  const router = useRouter();
  const [userData, setUserData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  
  const [upiId, setUpiId] = useState('');
  const [gmailEmail, setGmailEmail] = useState('');
  const [gmailPassword, setGmailPassword] = useState('');

  const BASE_URL = 'https://famdgtlapi.vercel.app'; // Tera API URL

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, async (user) => {
      if (user) {
        const docRef = doc(db, "merchants", user.uid);
        const docSnap = await getDoc(docRef);
        if (docSnap.exists()) {
          const data = docSnap.data();
          setUserData(data);
          setUpiId(data.upiId || '');
          setGmailEmail(data.gmailEmail || '');
          setGmailPassword(data.gmailPassword || '');
        }
      } else {
        router.push('/login');
      }
      setLoading(false);
    });
    return () => unsubscribe();
  }, [router]);

  const handleLogout = async () => {
    await signOut(auth);
    router.push('/login');
  };

  const handleSaveSettings = async () => {
    setSaving(true);
    try {
      await updateDoc(doc(db, "merchants", auth.currentUser.uid), {
        upiId, gmailEmail, gmailPassword
      });
      alert("Payment Settings Saved Successfully! ✅");
    } catch (error) {
      alert("Error saving settings");
    }
    setSaving(false);
  };

  if (loading) return <div className="min-h-screen bg-slate-950 text-white flex items-center justify-center">Loading...</div>;

  return (
    <div className="min-h-screen bg-slate-950 text-white flex">
      <Head><title>Merchant Dashboard · FampayApiDgtl</title></Head>

      {/* Sidebar (SaaS Style) */}
      <div className="w-64 bg-slate-900 border-r border-white/10 hidden md:flex flex-col">
        <div className="p-6 text-xl font-black text-purple-400">FampayApiDgtl</div>
        <nav className="flex-1 px-4 space-y-2">
          <a href="#" className="block px-4 py-2 bg-purple-600/20 text-purple-400 rounded-lg">Overview</a>
          <a href="#" className="block px-4 py-2 hover:bg-white/5 rounded-lg transition">Transactions</a>
          <a href="#" className="block px-4 py-2 hover:bg-white/5 rounded-lg transition">API Keys</a>
          <a href="#" className="block px-4 py-2 hover:bg-white/5 rounded-lg transition">Settings</a>
        </nav>
        <div className="p-4 border-t border-white/10">
          <button onClick={handleLogout} className="w-full text-left px-4 py-2 text-red-400 hover:bg-red-500/10 rounded-lg">Logout</button>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 p-6 md:p-10 overflow-y-auto">
        <div className="max-w-5xl mx-auto space-y-6">
          
          <div className="flex justify-between items-end">
            <div>
              <h1 className="text-3xl font-bold">Welcome, {userData?.email?.split('@')[0]} 👋</h1>
              <p className="text-slate-400 mt-1">Manage your payment gateway here.</p>
            </div>
          </div>

          {/* API Key Section */}
          <div className="bg-slate-900 border border-white/10 p-6 rounded-2xl shadow-xl relative overflow-hidden">
            <div className="absolute top-0 right-0 w-32 h-32 bg-purple-500/10 blur-3xl rounded-full"></div>
            <h2 className="text-sm font-semibold text-slate-400 mb-2">Live API Key (Keep it secret)</h2>
            <div className="flex items-center gap-3">
              <code className="bg-black/50 border border-white/10 px-4 py-3 rounded-xl text-emerald-400 font-mono text-sm flex-1">
                {userData?.apiKey}
              </code>
              <button onClick={() => { navigator.clipboard.writeText(userData.apiKey); alert('Copied!'); }} className="bg-emerald-600 hover:bg-emerald-500 px-4 py-3 rounded-xl font-bold transition-all">
                Copy
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            
            {/* Settings Form */}
            <div className="bg-slate-900 border border-white/10 p-6 rounded-2xl shadow-xl">
              <h2 className="text-lg font-bold mb-4 text-white">⚙️ Payment Configuration</h2>
              <p className="text-xs text-slate-400 mb-6">Yahan apni details daalein. Paisa seedha aapke UPI me aayega.</p>
              
              <div className="space-y-4">
                <div>
                  <label className="block text-xs font-bold text-slate-400 mb-1.5 uppercase">Your UPI ID</label>
                  <input type="text" value={upiId} onChange={(e) => setUpiId(e.target.value)} placeholder="yourname@fam" className="w-full bg-black/50 border border-white/10 rounded-xl px-4 py-3 text-white focus:border-purple-500 outline-none transition-colors" />
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-400 mb-1.5 uppercase">Gmail Address</label>
                  <input type="email" value={gmailEmail} onChange={(e) => setGmailEmail(e.target.value)} placeholder="your@gmail.com" className="w-full bg-black/50 border border-white/10 rounded-xl px-4 py-3 text-white focus:border-purple-500 outline-none transition-colors" />
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-400 mb-1.5 uppercase">Gmail App Password</label>
                  <input type="password" value={gmailPassword} onChange={(e) => setGmailPassword(e.target.value)} placeholder="16-character password" className="w-full bg-black/50 border border-white/10 rounded-xl px-4 py-3 text-white focus:border-purple-500 outline-none transition-colors" />
                </div>
                <button onClick={handleSaveSettings} disabled={saving} className="w-full bg-purple-600 hover:bg-purple-500 text-white font-bold py-3 rounded-xl mt-2 transition-all">
                  {saving ? 'Saving...' : 'Save Configuration'}
                </button>
              </div>
            </div>

            {/* API Docs */}
            <div className="bg-slate-900 border border-white/10 p-6 rounded-2xl shadow-xl">
              <h2 className="text-lg font-bold mb-4 text-white">📚 API Documentation</h2>
              
              <div className="space-y-4">
                <div className="bg-black/50 p-4 rounded-xl border border-white/5">
                  <div className="flex items-center gap-2 mb-2">
                    <span className="bg-emerald-500/20 text-emerald-400 text-[10px] font-bold px-2 py-0.5 rounded">GET</span>
                    <h3 className="text-sm font-bold text-slate-200">Create Order</h3>
                  </div>
                  <code className="text-xs text-purple-300 block bg-black p-3 rounded-lg overflow-x-auto whitespace-pre">
                    {BASE_URL}/?api_key={userData?.apiKey}&amount=100
                  </code>
                </div>

                <div className="bg-black/50 p-4 rounded-xl border border-white/5">
                  <div className="flex items-center gap-2 mb-2">
                    <span className="bg-blue-500/20 text-blue-400 text-[10px] font-bold px-2 py-0.5 rounded">GET</span>
                    <h3 className="text-sm font-bold text-slate-200">Check Status</h3>
                  </div>
                  <code className="text-xs text-purple-300 block bg-black p-3 rounded-lg overflow-x-auto whitespace-pre">
                    {BASE_URL}/?action=check&api_key={userData?.apiKey}&order_id=ORD_ID&amount=100
                  </code>
                </div>
              </div>
            </div>

          </div>
        </div>
      </div>
    </div>
  );
    }
