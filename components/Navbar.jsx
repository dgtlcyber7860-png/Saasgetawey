import { useState } from 'react';
import Link from 'next/link';
import { Menu, X } from 'lucide-react'; // Agar lucide-react nahi hai toh `npm i lucide-react` kar lena

export default function Navbar() {
  const [isOpen, setIsOpen] = useState(false);

  const menuItems = [
    { name: 'How it works', href: '#how-it-works' },
    { name: 'API', href: '/api-docs' },
    { name: 'Architecture', href: '#architecture' },
    { name: 'Docs', href: '/docs' },
    { name: 'Blog', href: '/blog' },
    { name: 'Reports', href: '/reports' },
  ];

  return (
    <nav className="fixed top-0 w-full z-50 bg-[#0B1120]/80 backdrop-blur-md border-b border-white/5">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-20">
          
          {/* Logo */}
          <Link href="/" className="flex items-center gap-2">
            <div className="w-8 h-8 bg-blue-500 rounded-lg flex items-center justify-center">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M4 12C4 7.58172 7.58172 4 12 4H20M4 12H12M4 12V20M4 16H12" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </div>
            <span className="text-xl font-bold tracking-tight">
              Fam<span className="text-blue-500">Gateway</span><span className="text-[10px] align-super text-slate-400">™</span>
            </span>
          </Link>

          {/* Desktop Menu (Badi screen ke liye) */}
          <div className="hidden md:flex items-center space-x-8">
            {menuItems.map((item) => (
              <Link key={item.name} href={item.href} className="text-sm text-slate-300 hover:text-white transition-colors">
                {item.name}
              </Link>
            ))}
            <div className="flex items-center gap-4 ml-4 border-l border-white/10 pl-6">
              <Link href="/login" className="text-sm font-semibold text-white hover:text-blue-400">Log in</Link>
              <Link href="/login" className="text-sm font-semibold bg-blue-600 hover:bg-blue-500 px-5 py-2.5 rounded-lg transition-all">Register</Link>
            </div>
          </div>

          {/* Mobile Menu Button (Hamburger) */}
          <div className="md:hidden flex items-center">
            <button onClick={() => setIsOpen(!isOpen)} className="text-slate-300 hover:text-white p-2">
              {isOpen ? <X size={24} /> : <Menu size={24} />}
            </button>
          </div>
        </div>
      </div>

      {/* Mobile Menu (Jab hamburger dabaye) */}
      {isOpen && (
        <div className="md:hidden bg-[#0B1120] border-b border-white/10 absolute w-full left-0 top-20 shadow-2xl">
          <div className="px-4 pt-2 pb-6 space-y-1">
            {menuItems.map((item) => (
              <Link key={item.name} href={item.href} onClick={() => setIsOpen(false)} className="block px-3 py-4 text-base font-medium text-slate-300 hover:text-white hover:bg-white/5 rounded-lg border-b border-white/5 last:border-0">
                {item.name}
              </Link>
            ))}
            <div className="mt-6 flex flex-col gap-3 px-3">
              <Link href="/login" onClick={() => setIsOpen(false)} className="w-full text-center py-3 rounded-xl border border-white/20 text-white font-semibold">Login</Link>
              <Link href="/login" onClick={() => setIsOpen(false)} className="w-full text-center py-3 rounded-xl bg-blue-600 text-white font-semibold shadow-[0_0_15px_rgba(37,99,235,0.3)]">Register</Link>
            </div>
          </div>
        </div>
      )}
    </nav>
  );
}
