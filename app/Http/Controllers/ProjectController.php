<?php

namespace App\Http\Controllers;

use App\Exceptions\EmpyPlanningException;
use App\Models\Project;
use App\Services\Empy\ProjectImportService;
use Illuminate\Http\RedirectResponse;
use Illuminate\Http\Request;
use Illuminate\View\View;

class ProjectController extends Controller
{
    public function index(): View
    {
        return view('dashboard', ['projects' => Project::query()->latest()->withCount('tickets')->get()]);
    }

    public function show(Project $project): View
    {
        return view('projects.show', ['project' => $project->load(['tickets' => fn ($query) => $query->latest()])]);
    }

    public function store(Request $request, ProjectImportService $imports): RedirectResponse
    {
        $data = $request->validate([
            'name' => ['nullable', 'string', 'max:120'],
            'archive' => ['required', 'file', 'mimes:zip', 'max:102400'],
        ]);
        try {
            $project = $imports->import($request->file('archive'), $data['name'] ?? null);
        } catch (\Throwable $exception) {
            return back()->withInput()->with('error', $this->plainError($exception));
        }

        return redirect()->route('projects.show', $project)->with('success', 'پروژه با workspace مستقل وارد شد و آمادهٔ Ticket است.');
    }

    private function plainError(\Throwable $exception): string
    {
        if ($exception instanceof EmpyPlanningException) {
            return 'برنامه‌ریزی انجام نشد: '.$exception->getMessage();
        }

        return 'ورود پروژه انجام نشد: '.$exception->getMessage();
    }
}
