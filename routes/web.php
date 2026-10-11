<?php

use App\Http\Controllers\ProjectController;
use App\Http\Controllers\TicketController;
use Illuminate\Support\Facades\Route;

Route::get('/', [ProjectController::class, 'index'])->name('dashboard');
// Keep the collection URL safe to revisit after a form submit or browser reload.
// Project creation remains POST-only; GET /projects shows the same dashboard.
Route::get('/projects', [ProjectController::class, 'index'])->name('projects.index');
Route::post('/projects', [ProjectController::class, 'store'])->name('projects.store');
Route::get('/projects/{project}', [ProjectController::class, 'show'])->name('projects.show');
Route::post('/projects/{project}/tickets', [TicketController::class, 'store'])->name('tickets.store');
Route::post('/tickets/{ticket}/execute', [TicketController::class, 'execute'])->name('tickets.execute');
Route::post('/tickets/{ticket}/verify', [TicketController::class, 'verify'])->name('tickets.verify');
Route::post('/tickets/{ticket}/deliver', [TicketController::class, 'deliver'])->name('tickets.deliver');
Route::get('/artifacts/{artifact}/download', [TicketController::class, 'download'])->name('artifacts.download');
